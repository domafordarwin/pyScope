# app/capture/camera_worker.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CameraWorker — opens a USB UVC camera with V4L2 + MJPG and emits frames.

Improvements over the naive `cv2.VideoCapture(0)` pattern:
  * Explicit V4L2 backend (skips slow GStreamer fallback on Linux/Pi)
  * MJPG fourcc (lets USB 2.0 cameras run at full FPS up to 5MP)
  * Auto-discovery of /dev/video* (no hard-coded index)
  * Reads back actual width/height/fps after set() (cameras downgrade silently)
  * Verbose error reporting (status signal includes tried indices, errno hint)
  * Disconnect detection (30 consecutive read failures stops the loop)
"""

import os
import re
import time
import glob
import subprocess
import cv2
from PyQt5 import QtCore


# Korean / European AC = 50 Hz, North America = 60 Hz.
# Override via env var: RAIM_AC_HZ=60 .venv/bin/python -m app.main
AC_LINE_HZ_DEFAULT = 50


# =====================================================================
# Camera classification — microscope cameras vs generic USB webcams
# =====================================================================
# 카메라마다 적정 노출/게인/안티-flicker 전략이 달라서, 시작 시 자동 분류 후
# 프로파일을 적용한다. 환경변수가 있으면 항상 환경변수가 최우선.

# 알려진 현미경 카메라의 USB vendor:product ID
MICROSCOPE_USB_IDS = {
    "0ac8:3420",   # FIC OS-CM50 (5MP USB 현미경 카메라)
    "1e4e:0109",   # Cubeternet eSP570 (Onyx Titanium TC101)
    # 새 모델 추가 시 여기에:
    # "vvvv:pppp",  # 모델 설명
}

# 카메라 이름(/sys/class/video4linux/.../name)에 포함될 수 있는 현미경 키워드
MICROSCOPE_NAME_KEYWORDS = (
    "OS-CM50", "Cubeternet", "eSP570", "Onyx Titanium",
    "AmScope", "Motic", "Microscope", "Eyepiece",
    "Toupcam", "MShot", "ToupTek",
)

# Profile name → v4l2 control values (적용 가능한 것만 시도; 미지원 컨트롤은 silent fail)
CAMERA_PROFILES = {
    "microscope": {
        # Sense HAT LED 강한 광원 + PWM banding 방지 + 30fps 라이브뷰
        "power_line_frequency":       1,    # 50Hz
        "auto_exposure":              1,    # Manual mode
        "exposure_time_absolute":     200,  # 20 ms (PWM ≥100Hz averaging)
        "gain":                       24,
        "brightness":                 12,   # 일반 1-16 범위 가정
        "exposure_dynamic_framerate": 0,    # 고정 fps (DPC 시퀀스에 중요)
    },
    "general": {
        # 다양한 실내 조명 / 역광 환경 자동 대응
        "power_line_frequency":       1,    # 50Hz
        "auto_exposure":              3,    # Aperture Priority (auto)
        "backlight_compensation":     2,    # 역광 보정 최대
        "brightness":                 0,    # 카메라 default 사용
        "exposure_dynamic_framerate": 1,    # 자동 fps 조정 허용
    },
}

# 환경변수 오버라이드 (있으면 프로필 값을 덮어씀)
AUTO_EXPOSURE_DEFAULT   = None       # None = 카메라 분류로 결정
EXPOSURE_X100US_DEFAULT = None
GAIN_DEFAULT            = None
BRIGHTNESS_DEFAULT      = None


class CameraWorker(QtCore.QObject):
    frame_ready          = QtCore.pyqtSignal(object)  # numpy ndarray (BGR)
    status               = QtCore.pyqtSignal(str)
    controls_detected    = QtCore.pyqtSignal(dict)    # v4l2 controls + ranges
    profile_applied      = QtCore.pyqtSignal(dict)    # {kind, name, profile}

    def __init__(self, cam_index=None, width=2592, height=1944, fps=30,
                 gui_emit_fps=15):
        """
        Defaults target FIC OS-CM50 maximum native mode (5 MP MJPG @ 30 fps).
        The driver silently downgrades unsupported sizes to the closest match,
        so generic UVC webcams will negotiate down to 1080p / 720p / 480p
        without breakage. Read self.actual_{width,height,fps} after start()
        to see what was actually negotiated.

        Capture rate (`fps`) and GUI emit rate (`gui_emit_fps`) are decoupled:
          * The camera reads at full `fps` so DPC capture always has a fresh frame.
          * The frame_ready signal is throttled to `gui_emit_fps` to avoid
            saturating the GUI thread with multi-MP conversions.
          * Default 15 Hz GUI emit is plenty for a microscopy live view and
            keeps a Pi 5 responsive at 5 MP.

        cam_index=None  -> auto-discover (try /dev/video0..9)
        cam_index=N     -> use this specific index, fall back to auto-scan on failure

        Lower defaults if CPU is still saturated:
          CameraWorker(width=1600, height=1200, fps=30)   # 2 MP, lighter
          CameraWorker(width=1280, height=800,  fps=30)   # 1 MP, lightest
        """
        super().__init__()
        self.cam_index = cam_index
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.gui_emit_fps = int(gui_emit_fps)
        self._running = False
        self.cap = None

        # populated after start() succeeds
        self.actual_index = None
        self.actual_width = None
        self.actual_height = None
        self.actual_fps = None

    # ---------- helpers ----------
    @staticmethod
    def _list_video_indices():
        """Return sorted indices of /dev/video* nodes (low numbers first)."""
        out = []
        for p in glob.glob("/dev/video*"):
            tail = p.replace("/dev/video", "")
            if tail.isdigit():
                out.append(int(tail))
        return sorted(out)

    @staticmethod
    def _v4l2_set(device, ctrl, val):
        try:
            subprocess.run(
                ["v4l2-ctl", "-d", device, "--set-ctrl=%s=%s" % (ctrl, val)],
                check=False,
                capture_output=True,
                timeout=2,
            )
        except Exception:
            pass

    @staticmethod
    def list_v4l2_controls(index):
        """
        v4l2-ctl --list-ctrls 결과를 파싱해 사용 가능한 컨트롤 + 범위를 반환.

        반환 예시::
            {
              "brightness": {"type": "int", "min": -64, "max": 64,
                              "step": 1, "default": 0, "value": 12},
              "auto_exposure": {"type": "menu", "min": 0, "max": 3,
                                 "default": 3, "value": 1},
              ...
            }

        실패 시 빈 dict.
        """
        device = "/dev/video%d" % index
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-d", device, "--list-ctrls"],
                check=False, capture_output=True, text=True, timeout=2,
            )
            text = result.stdout
        except Exception:
            return {}

        # 한 줄 예시:
        #   brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=12
        line_re = re.compile(
            r"^\s+(\w+)\s+0x[0-9a-fA-F]+\s+\((\w+)\)"
            r"(?:\s+flags=\w+)?\s*:\s*(.*)$"
        )
        kv_re = re.compile(r"(\w+)=(-?\d+)")
        controls = {}
        for line in text.split("\n"):
            m = line_re.match(line)
            if not m:
                continue
            name, ctype, params = m.groups()
            info = {"type": ctype}
            for k, v in kv_re.findall(params):
                try:
                    info[k] = int(v)
                except ValueError:
                    pass
            controls[name] = info
        return controls

    # V4L2 컨트롤 이름 → cv2 CAP_PROP 매핑.
    # cv2.set 은 cap 점유 중에 안전하게 동작하는 반면, v4l2-ctl 서브프로세스는
    # 같은 디바이스를 cv2가 잡고 있으면 silent fail 할 수 있음.
    _CV2_PROP_MAP = {
        "exposure_time_absolute":  cv2.CAP_PROP_EXPOSURE,
        "auto_exposure":           cv2.CAP_PROP_AUTO_EXPOSURE,
        "brightness":              cv2.CAP_PROP_BRIGHTNESS,
        "contrast":                cv2.CAP_PROP_CONTRAST,
        "gain":                    cv2.CAP_PROP_GAIN,
        "gamma":                   cv2.CAP_PROP_GAMMA,
        "backlight_compensation":  cv2.CAP_PROP_BACKLIGHT,
        "saturation":              cv2.CAP_PROP_SATURATION,
        "hue":                     cv2.CAP_PROP_HUE,
        "sharpness":               cv2.CAP_PROP_SHARPNESS,
    }

    @QtCore.pyqtSlot(str, int)
    def set_v4l2_control(self, name, value):
        """
        런타임 v4l2 컨트롤 변경 (GUI 슬라이더에서 호출).

        전략:
          1) cv2.set(CAP_PROP_*) — cap이 열린 상태에서 즉시 적용, 충돌 없음
          2) cv2 매핑 없거나 실패 → v4l2-ctl subprocess fallback
          3) 적용 후 v4l2-ctl --get-ctrl 로 검증 + 상태 시그널 emit
        """
        if self.actual_index is None:
            self.status.emit("카메라 컨트롤 실패: 카메라 미시작")
            return

        device = "/dev/video%d" % self.actual_index
        applied_via = None

        # ---- 1) cv2.set 우선 ----
        if self.cap is not None and name in self._CV2_PROP_MAP:
            try:
                ok = self.cap.set(self._CV2_PROP_MAP[name], float(value))
                if ok:
                    applied_via = "cv2"
            except Exception:
                pass

        # ---- 2) v4l2-ctl fallback ----
        if applied_via is None:
            try:
                result = subprocess.run(
                    ["v4l2-ctl", "-d", device,
                     "--set-ctrl=%s=%d" % (name, int(value))],
                    check=False, capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0:
                    applied_via = "v4l2-ctl"
                else:
                    err = (result.stderr or "").strip().splitlines()
                    msg = err[0] if err else "rc=%d" % result.returncode
                    self.status.emit(
                        "카메라 컨트롤 실패 %s=%d : %s" % (name, value, msg[:60])
                    )
                    return
            except Exception as e:
                self.status.emit(
                    "카메라 컨트롤 예외 %s=%d : %s" % (name, value, str(e)[:60])
                )
                return

        # ---- 3) 검증: 실제 카메라가 받은 값 확인 ----
        try:
            verify = subprocess.run(
                ["v4l2-ctl", "-d", device, "--get-ctrl=%s" % name],
                check=False, capture_output=True, text=True, timeout=2,
            )
            line = (verify.stdout or "").strip()
            # 예: "exposure_time_absolute: 8780"
            if ":" in line:
                actual = line.split(":", 1)[1].strip().split()[0]
                self.status.emit(
                    "카메라: %s = %s (요청 %d, %s)" %
                    (name, actual, value, applied_via)
                )
        except Exception:
            pass

    @QtCore.pyqtSlot()
    def apply_hi_mag_boost(self):
        """400배 등 고배율 환경 빛량 부스트.

        노출 50ms + gain ↑ + brightness max. LED PWM banding 가능성을
        감수하더라도 빛량 우선 — 시료가 어두워서 보이지 않는 것보다 낫다.
        존재하지 않는 컨트롤은 set_v4l2_control 이 silent fail 한다.
        """
        if self.actual_index is None:
            self.status.emit("고배율 부스트 실패: 카메라 미시작")
            return
        # auto exposure off (manual) → 노출 시간 직접 적용
        self.set_v4l2_control("auto_exposure",            1)
        self.set_v4l2_control("exposure_time_absolute", 500)   # 50 ms
        self.set_v4l2_control("gain",                    80)
        self.set_v4l2_control("brightness",              16)   # 일반 1-16
        # 일반 웹캠 — backlight_compensation 도 같이 max
        self.set_v4l2_control("backlight_compensation",   2)
        self.status.emit(
            "🔆 고배율 부스트 — 노출 50ms · gain 80 · brightness max"
        )

    @staticmethod
    def _read_camera_name(index):
        """/sys/class/video4linux/videoN/name 에서 카메라 product name."""
        try:
            with open("/sys/class/video4linux/video%d/name" % index, "r") as f:
                return f.read().strip()
        except Exception:
            return ""

    @staticmethod
    def _list_lsusb_lines():
        """lsusb 결과 라인 리스트 (분류용)."""
        try:
            r = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=2,
            )
            return [ln.strip() for ln in r.stdout.split("\n") if ln.strip()]
        except Exception:
            return []

    @classmethod
    def detect_camera_kind(cls, index):
        """
        카메라가 현미경용 (microscope) 인지 일반 USB 웹캠 (general) 인지 분류.

        판정 순서:
          1) USB vendor:product ID 가 알려진 현미경 모델 화이트리스트에 있으면 microscope
          2) 카메라 product name (sysfs 또는 lsusb 라인) 에 현미경 키워드 포함되면 microscope
          3) 둘 다 아니면 general (일반 USB 웹캠)
        """
        name = cls._read_camera_name(index)
        usb_lines = cls._list_lsusb_lines()

        # 1) USB ID 매치
        for vid_pid in MICROSCOPE_USB_IDS:
            if any(vid_pid in ln for ln in usb_lines):
                return "microscope", name or vid_pid

        # 2) 이름 키워드 매치 (sysfs name)
        name_lower = name.lower()
        for kw in MICROSCOPE_NAME_KEYWORDS:
            if kw.lower() in name_lower:
                return "microscope", name

        # 2-b) 이름 키워드 매치 (lsusb 라인 — sysfs가 generic할 때)
        for ln in usb_lines:
            for kw in MICROSCOPE_NAME_KEYWORDS:
                if kw.lower() in ln.lower():
                    return "microscope", ln

        # 3) 일반 USB 웹캠
        return "general", name or "USB Camera"

    def _apply_v4l2_optimizations(self, index):
        """
        카메라 종류 자동 분류 → 프로파일 적용 → 환경변수 오버라이드.

        Profile 적용:
          - microscope: 수동 노출 20ms + gain ↑ + anti-flicker (Sense HAT LED 환경)
          - general   : 자동 노출 + 역광 보정 max (실내 조명 / 역광 자동 적응)

        환경변수 (RAIM_*)는 항상 프로파일을 덮어쓴다.
        """
        device = "/dev/video%d" % index

        # 1) 카메라 분류
        kind, name = self.detect_camera_kind(index)
        profile = dict(CAMERA_PROFILES.get(kind, CAMERA_PROFILES["general"]))

        # 2) AC 주파수 환경변수
        if "RAIM_AC_HZ" in os.environ:
            try:
                ac_hz = int(os.environ["RAIM_AC_HZ"])
                profile["power_line_frequency"] = 1 if ac_hz == 50 else 2
            except ValueError:
                pass

        # 3) 노출 모드 환경변수
        if "RAIM_AUTO_EXPOSURE" in os.environ:
            mode = os.environ["RAIM_AUTO_EXPOSURE"].lower()
            profile["auto_exposure"] = 1 if mode == "manual" else 3
            # 자동으로 변경 시 수동 노출/게인 키 제거 (의미 없음)
            if mode != "manual":
                profile.pop("exposure_time_absolute", None)
                profile.pop("gain", None)

        # 4) 노출 시간 환경변수 (Manual 모드에서만 의미)
        if "RAIM_EXPOSURE_X100US" in os.environ and \
                profile.get("auto_exposure") == 1:
            try:
                profile["exposure_time_absolute"] = \
                    int(os.environ["RAIM_EXPOSURE_X100US"])
            except ValueError:
                pass

        # 5) 게인 환경변수
        if "RAIM_GAIN" in os.environ:
            try:
                profile["gain"] = int(os.environ["RAIM_GAIN"])
            except ValueError:
                pass

        # 6) 밝기 환경변수
        if "RAIM_BRIGHTNESS" in os.environ:
            try:
                profile["brightness"] = int(os.environ["RAIM_BRIGHTNESS"])
            except ValueError:
                pass

        # 7) 프로파일 모든 컨트롤 적용 (실패해도 silent — 미지원 카메라엔 자동 skip)
        for ctrl, val in profile.items():
            self._v4l2_set(device, ctrl, str(int(val)))

        # 8) 상태 알림 + GUI 시그널
        kind_kr = "현미경 카메라" if kind == "microscope" else "일반 USB 카메라"
        self.status.emit(
            "카메라 프로파일 적용: %s (%s) — %s" %
            (kind_kr, name, ", ".join("%s=%s" % (k, v)
                                       for k, v in profile.items()))[:200]
        )
        self.profile_applied.emit({
            "kind": kind,
            "kind_kr": kind_kr,
            "name": name,
            "profile": profile,
        })

    def _open_camera(self, index):
        """Try to open camera at index with V4L2 + MJPG. Returns capture or None."""
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not cap.isOpened():
            return None

        # Force MJPG — critical for high-res USB cameras (e.g., OS-CM50 5MP@30fps)
        try:
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        except Exception:
            pass

        # Minimal internal buffer — V4L2 / cv2 normally hold ~5 frames in queue,
        # which on a slower decode pipeline introduces seconds of perceived lag
        # ("frozen view" symptom). BUFFERSIZE=1 forces always-latest-frame.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)

        # Anti-flicker etc. — must apply BEFORE the verify-read below
        self._apply_v4l2_optimizations(index)

        # Verify with a real read — open() can succeed but read() may fail
        # (driver loaded but format unsupported, etc.)
        ok, _ = cap.read()
        if not ok:
            cap.release()
            return None
        return cap

    # ---------- Qt slots ----------
    @QtCore.pyqtSlot()
    def start(self):
        self._running = True

        # Build candidate index list
        if self.cam_index is not None:
            candidates = [self.cam_index]
            # If explicit index fails, also try auto-scan as fallback
            for i in self._list_video_indices():
                if i != self.cam_index and i < 10:
                    candidates.append(i)
        else:
            scanned = [i for i in self._list_video_indices() if i < 10]
            if not scanned:
                # Fall back to brute-force 0..9
                scanned = list(range(10))
            candidates = scanned

        if not candidates:
            self.status.emit(
                "카메라 열기 실패: /dev/video* 노드가 없습니다. "
                "USB 카메라가 연결되어 있는지 확인하세요."
            )
            self._running = False
            return

        self.status.emit(
            "카메라 탐색 중... (시도: %s)" % ", ".join(map(str, candidates))
        )

        # Try each candidate
        opened_index = None
        for idx in candidates:
            self.cap = self._open_camera(idx)
            if self.cap is not None:
                opened_index = idx
                break

        if self.cap is None:
            self.status.emit(
                "카메라 열기 실패 (시도한 인덱스: %s). "
                "lsusb로 카메라 연결 상태를 확인하세요." % ", ".join(map(str, candidates))
            )
            self._running = False
            return

        # Read back what the driver actually negotiated
        self.actual_index  = opened_index
        self.actual_width  = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.actual_fps    = self.cap.get(cv2.CAP_PROP_FPS)

        # v4l2 컨트롤 목록 + 현재 값 → GUI 카메라 패널에 전달
        controls = self.list_v4l2_controls(opened_index)
        if controls:
            self.controls_detected.emit(controls)
        try:
            fcc_int = int(self.cap.get(cv2.CAP_PROP_FOURCC))
            fourcc_str = "".join([chr((fcc_int >> 8 * i) & 0xFF) for i in range(4)])
        except Exception:
            fourcc_str = "?"

        self.status.emit(
            "카메라 시작: /dev/video%d  %dx%d @ %.0ffps  포맷=%s" % (
                opened_index,
                self.actual_width, self.actual_height,
                self.actual_fps if self.actual_fps > 0 else 0,
                fourcc_str,
            )
        )

        # Pace by actual fps (camera may have downgraded)
        eff_fps = self.actual_fps if self.actual_fps and self.actual_fps > 0 else self.fps
        interval = 1.0 / max(eff_fps, 1)
        gui_interval = 1.0 / max(self.gui_emit_fps, 1)

        consecutive_failures = 0
        last_gui_emit = 0.0
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                consecutive_failures += 1
                if consecutive_failures == 1:
                    self.status.emit("프레임 읽기 실패 — 재시도 중")
                if consecutive_failures > 30:
                    self.status.emit(
                        "프레임 읽기 30회 연속 실패 — 카메라 분리 가능성. 중단합니다."
                    )
                    break
                time.sleep(0.05)
                continue
            consecutive_failures = 0

            # Throttle GUI emit so 5MP frames don't saturate the Qt thread.
            # Camera keeps reading at full fps so DPC capture sees fresh data.
            now = time.monotonic()
            if now - last_gui_emit >= gui_interval:
                self.frame_ready.emit(frame)
                last_gui_emit = now

            time.sleep(interval)

        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.status.emit("카메라 정지")

    @QtCore.pyqtSlot()
    def stop(self):
        self._running = False
