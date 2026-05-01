# app/ui/camera_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CameraPanel — 카메라 V4L2 컨트롤 (노출 / 게인 / 밝기) 런타임 조정 패널.

카메라 시작 후 `update_from_camera(controls_dict)` 가 호출되면 사용 가능한
컨트롤만 자동으로 표시되고, 슬라이더 범위는 카메라가 보고한 실제 min/max로
설정됩니다. OS-CM50처럼 gain이 있는 카메라와 Realtek처럼 gain이 없는 카메라
모두 호환됩니다.

시그널:
  control_changed(str name, int value) — 슬라이더 변경 시 emit
  → MainWindow에서 받아 CameraWorker.set_v4l2_control() 호출
"""

from PyQt5 import QtCore, QtWidgets

from .style import Color, make_separator


# v4l2 auto_exposure menu values (UVC 표준)
AE_MANUAL = 1
AE_APERTURE_PRIORITY = 3


class CameraPanel(QtWidgets.QGroupBox):
    """카메라 v4l2 컨트롤 — 동적 감지 기반 슬라이더 패널."""

    control_changed = QtCore.pyqtSignal(str, int)  # ctrl_name, value

    def __init__(self, parent=None):
        super().__init__("카메라  ·  V4L2 설정", parent)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        # ---- placeholder when no camera ----
        self.lbl_no_cam = QtWidgets.QLabel(
            "카메라 시작 후 이 패널에 사용 가능한 컨트롤이 표시됩니다."
        )
        self.lbl_no_cam.setProperty("role", "muted")
        self.lbl_no_cam.setWordWrap(True)
        root.addWidget(self.lbl_no_cam)

        # ---- auto exposure toggle ----
        self.chk_auto_exp = QtWidgets.QCheckBox("자동 노출")
        self.chk_auto_exp.setToolTip(
            "체크 해제: 수동 노출 — PWM 광원 banding 방지 (현미경 권장)\n"
            "체크: 자동 노출 — 일반 환경 광원에 자동 적응"
        )
        self.chk_auto_exp.toggled.connect(self._on_auto_exposure)
        self.chk_auto_exp.hide()
        root.addWidget(self.chk_auto_exp)

        # ---- exposure time slider ----
        self.exp_widget, self.sld_exp, self.lbl_exp = self._build_slider_block(
            "노출 시간", "ms",
            self._on_exp_value_changed, self._on_exp_released,
        )
        self.exp_widget.hide()
        root.addWidget(self.exp_widget)

        # ---- brightness slider ----
        self.br_widget, self.sld_br, self.lbl_br = self._build_slider_block(
            "밝기 (Brightness)", "",
            self._on_br_value_changed, self._on_br_released,
        )
        self.br_widget.hide()
        root.addWidget(self.br_widget)

        # ---- gain slider ----
        self.gn_widget, self.sld_gn, self.lbl_gn = self._build_slider_block(
            "게인 (Gain)", "",
            self._on_gn_value_changed, self._on_gn_released,
        )
        self.gn_widget.hide()
        root.addWidget(self.gn_widget)

        # ---- contrast slider ----
        self.ct_widget, self.sld_ct, self.lbl_ct = self._build_slider_block(
            "대비 (Contrast)", "",
            self._on_ct_value_changed, self._on_ct_released,
        )
        self.ct_widget.hide()
        root.addWidget(self.ct_widget)

        # ---- backlight compensation (역광 보정) ----
        self.bl_widget, self.sld_bl, self.lbl_bl = self._build_slider_block(
            "역광 보정 (Backlight)", "",
            self._on_bl_value_changed, self._on_bl_released,
        )
        self.bl_widget.hide()
        root.addWidget(self.bl_widget)

        # ---- gamma ----
        self.gm_widget, self.sld_gm, self.lbl_gm = self._build_slider_block(
            "감마 (Gamma)", "",
            self._on_gm_value_changed, self._on_gm_released,
        )
        self.gm_widget.hide()
        root.addWidget(self.gm_widget)

        # ---- reset button ----
        self.btn_reset = QtWidgets.QPushButton("기본값으로 복원")
        self.btn_reset.setProperty("role", "ghost")
        self.btn_reset.hide()
        self.btn_reset.clicked.connect(self._on_reset)
        root.addWidget(self.btn_reset)

        # ---- state ----
        self._has_auto_exp   = False
        self._has_exp_time   = False
        self._has_brightness = False
        self._has_gain       = False
        self._has_contrast   = False
        self._has_backlight  = False
        self._has_gamma      = False
        self._defaults       = {}   # ctrl_name -> default value

    # ----------------------------------------------------------------
    # UI builder
    # ----------------------------------------------------------------
    def _build_slider_block(self, caption, unit_hint, on_value, on_released):
        """라벨 + 슬라이더 + 값 표시 한 줄 묶음 위젯."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        cap = QtWidgets.QLabel(caption)
        cap.setProperty("role", "caption")
        layout.addWidget(cap)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(0)
        slider.setSingleStep(1)
        value_lbl = QtWidgets.QLabel("0")
        value_lbl.setProperty("role", "value")
        value_lbl.setFixedWidth(70)
        value_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        slider.valueChanged.connect(on_value)
        slider.sliderReleased.connect(on_released)

        row.addWidget(slider, 1)
        row.addWidget(value_lbl)
        layout.addLayout(row)
        return widget, slider, value_lbl

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------
    def update_from_camera(self, controls: dict):
        """CameraWorker.controls_detected 시그널 핸들러."""
        self.lbl_no_cam.hide()
        self.btn_reset.show()

        # auto_exposure
        ae = controls.get("auto_exposure")
        if ae:
            self._has_auto_exp = True
            self.chk_auto_exp.show()
            cur = int(ae.get("value", AE_APERTURE_PRIORITY))
            self.chk_auto_exp.blockSignals(True)
            self.chk_auto_exp.setChecked(cur != AE_MANUAL)
            self.chk_auto_exp.blockSignals(False)
            self._defaults["auto_exposure"] = int(ae.get("default",
                                                          AE_APERTURE_PRIORITY))

        # exposure_time_absolute
        exp = controls.get("exposure_time_absolute")
        if exp:
            self._has_exp_time = True
            self.exp_widget.show()
            self._configure_slider(
                self.sld_exp, exp,
                fallback_min=50, fallback_max=10000, fallback_default=200,
            )
            self._update_exp_label(self.sld_exp.value())
            self._defaults["exposure_time_absolute"] = int(
                exp.get("default", 200)
            )

        # brightness
        br = controls.get("brightness")
        if br:
            self._has_brightness = True
            self.br_widget.show()
            self._configure_slider(
                self.sld_br, br,
                fallback_min=-64, fallback_max=64, fallback_default=0,
            )
            self.lbl_br.setText(str(self.sld_br.value()))
            self._defaults["brightness"] = int(br.get("default", 0))

        # gain
        gn = controls.get("gain")
        if gn:
            self._has_gain = True
            self.gn_widget.show()
            self._configure_slider(
                self.sld_gn, gn,
                fallback_min=0, fallback_max=63, fallback_default=8,
            )
            self.lbl_gn.setText(str(self.sld_gn.value()))
            self._defaults["gain"] = int(gn.get("default", 8))
        else:
            self._has_gain = False
            self.gn_widget.hide()

        # contrast
        ct = controls.get("contrast")
        if ct:
            self._has_contrast = True
            self.ct_widget.show()
            self._configure_slider(
                self.sld_ct, ct,
                fallback_min=0, fallback_max=64, fallback_default=32,
            )
            self.lbl_ct.setText(str(self.sld_ct.value()))
            self._defaults["contrast"] = int(ct.get("default", 32))
        else:
            self._has_contrast = False
            self.ct_widget.hide()

        # backlight_compensation (역광 보정 — 사람이 광원을 등졌을 때)
        bl = controls.get("backlight_compensation")
        if bl:
            self._has_backlight = True
            self.bl_widget.show()
            self._configure_slider(
                self.sld_bl, bl,
                fallback_min=0, fallback_max=2, fallback_default=1,
            )
            self.lbl_bl.setText(str(self.sld_bl.value()))
            self._defaults["backlight_compensation"] = int(bl.get("default", 1))
        else:
            self._has_backlight = False
            self.bl_widget.hide()

        # gamma (감마 보정 — 어두운 영역 들어올리기)
        gm = controls.get("gamma")
        if gm:
            self._has_gamma = True
            self.gm_widget.show()
            self._configure_slider(
                self.sld_gm, gm,
                fallback_min=100, fallback_max=500, fallback_default=300,
            )
            self.lbl_gm.setText(str(self.sld_gm.value()))
            self._defaults["gamma"] = int(gm.get("default", 300))
        else:
            self._has_gamma = False
            self.gm_widget.hide()

        # 노출 슬라이더는 자동 노출 OFF 일 때만 활성
        self._update_exp_enabled()

    def reset_to_no_camera(self):
        """카메라 정지 시 컨트롤 숨기고 placeholder 다시 표시."""
        self.chk_auto_exp.hide()
        self.exp_widget.hide()
        self.br_widget.hide()
        self.gn_widget.hide()
        self.ct_widget.hide()
        self.bl_widget.hide()
        self.gm_widget.hide()
        self.btn_reset.hide()
        self.lbl_no_cam.show()
        self._defaults.clear()

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    @staticmethod
    def _configure_slider(slider, info, fallback_min, fallback_max,
                          fallback_default):
        mn = int(info.get("min", fallback_min))
        mx = int(info.get("max", fallback_max))
        val = int(info.get("value", info.get("default", fallback_default)))
        # ensure sane order
        if mn > mx:
            mn, mx = mx, mn
        val = max(mn, min(mx, val))
        slider.blockSignals(True)
        slider.setRange(mn, mx)
        slider.setValue(val)
        slider.blockSignals(False)

    def _update_exp_label(self, raw_value):
        """exposure_time_absolute 단위는 100µs (=0.1ms). 보기 좋게 변환."""
        ms = raw_value * 0.1
        if ms >= 1000:
            self.lbl_exp.setText("%.2f s" % (ms / 1000.0))
        elif ms >= 10:
            self.lbl_exp.setText("%.0f ms" % ms)
        else:
            self.lbl_exp.setText("%.1f ms" % ms)

    def _update_exp_enabled(self):
        if not self._has_exp_time:
            return
        # auto exposure ON → 노출 시간 슬라이더 비활성
        if self._has_auto_exp:
            self.sld_exp.setEnabled(not self.chk_auto_exp.isChecked())
        else:
            self.sld_exp.setEnabled(True)

    # ----------------------------------------------------------------
    # Slot handlers
    # ----------------------------------------------------------------
    def _on_auto_exposure(self, on):
        v = AE_APERTURE_PRIORITY if on else AE_MANUAL
        self.control_changed.emit("auto_exposure", v)
        self._update_exp_enabled()

    def _on_exp_value_changed(self, v):
        self._update_exp_label(v)
        if not self.sld_exp.isSliderDown():
            self.control_changed.emit("exposure_time_absolute", v)

    def _on_exp_released(self):
        self.control_changed.emit("exposure_time_absolute", self.sld_exp.value())

    def _on_br_value_changed(self, v):
        self.lbl_br.setText(str(v))
        if not self.sld_br.isSliderDown():
            self.control_changed.emit("brightness", v)

    def _on_br_released(self):
        self.control_changed.emit("brightness", self.sld_br.value())

    def _on_gn_value_changed(self, v):
        self.lbl_gn.setText(str(v))
        if not self.sld_gn.isSliderDown():
            self.control_changed.emit("gain", v)

    def _on_gn_released(self):
        self.control_changed.emit("gain", self.sld_gn.value())

    def _on_ct_value_changed(self, v):
        self.lbl_ct.setText(str(v))
        if not self.sld_ct.isSliderDown():
            self.control_changed.emit("contrast", v)

    def _on_ct_released(self):
        self.control_changed.emit("contrast", self.sld_ct.value())

    def _on_bl_value_changed(self, v):
        self.lbl_bl.setText(str(v))
        if not self.sld_bl.isSliderDown():
            self.control_changed.emit("backlight_compensation", v)

    def _on_bl_released(self):
        self.control_changed.emit("backlight_compensation", self.sld_bl.value())

    def _on_gm_value_changed(self, v):
        self.lbl_gm.setText(str(v))
        if not self.sld_gm.isSliderDown():
            self.control_changed.emit("gamma", v)

    def _on_gm_released(self):
        self.control_changed.emit("gamma", self.sld_gm.value())

    def _on_reset(self):
        # auto_exposure 먼저 → 노출 슬라이더 활성 상태 결정
        if "auto_exposure" in self._defaults:
            ae_default = self._defaults["auto_exposure"]
            self.chk_auto_exp.blockSignals(True)
            self.chk_auto_exp.setChecked(ae_default != AE_MANUAL)
            self.chk_auto_exp.blockSignals(False)
            self.control_changed.emit("auto_exposure", ae_default)

        slider_map = {
            "exposure_time_absolute":   (self.sld_exp, self.lbl_exp, "exp"),
            "brightness":               (self.sld_br,  self.lbl_br,  "raw"),
            "gain":                     (self.sld_gn,  self.lbl_gn,  "raw"),
            "contrast":                 (self.sld_ct,  self.lbl_ct,  "raw"),
            "backlight_compensation":   (self.sld_bl,  self.lbl_bl,  "raw"),
            "gamma":                    (self.sld_gm,  self.lbl_gm,  "raw"),
        }
        for name, default in self._defaults.items():
            if name not in slider_map:
                continue
            slider, lbl, mode = slider_map[name]
            slider.blockSignals(True)
            slider.setValue(default)
            slider.blockSignals(False)
            self.control_changed.emit(name, default)
            if mode == "exp":
                self._update_exp_label(default)
            else:
                lbl.setText(str(default))

        self._update_exp_enabled()
