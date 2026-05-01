# app/ui/main_window.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAIM Scope MainWindow — 탭 기반 작업 흐름 v3.

레이아웃:
  ┌───────────────────────────────────────────┐
  │ HeaderBar                                  │
  │ Toolbar (전역 액션)                          │
  ├───────────────────────────────────────────┤
  │  LiveView (위쪽, 모든 탭 공통 표시)         │
  │  + ROI 정보 + 카메라 시작/정지 버튼          │
  ├───────────────────────────────────────────┤
  │ [📷 라이브][🏷️ 데이터셋][🤖 검출][📁 아카이브] │
  │ (탭 콘텐츠)                                 │
  └───────────────────────────────────────────┘
"""

import os
import cv2
from PyQt5 import QtCore, QtGui, QtWidgets

from ..capture.camera_worker import CameraWorker
from ..capture.capture_controller import CaptureController
from ..capture.sequence_repo import guess_seq_dir_from_image
from ..util.image_convert import crop_bgr

from .live_view import LiveView
from .preview import PreviewView
from .sense_panel import SensePanel
from .capture_panel import CapturePanel
from .camera_panel import CameraPanel
from .gallery_panel import GalleryPanel
from .player_panel import PlayerPanel
from .header_bar import HeaderBar
from .image_viewer import ImageViewerDialog
from .ai_panel import AIPanel
from .dataset_panel import DatasetPanel
from .detect_panel import DetectPanel
from .style import Color, make_separator

from ..ai import HAILO_OK
from ..ai.inference_worker import InferenceWorker


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAIM Scope  ·  탭 기반 작업 흐름 v3")
        self.resize(1500, 980)
        self.setMinimumSize(1280, 760)

        self._last_frame = None
        self._roi = None
        self._pending_save_all = False

        # ============ Central shell ============
        central = QtWidgets.QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        shell = QtWidgets.QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # ---- Header + Toolbar ----
        self.header = HeaderBar()
        shell.addWidget(self.header)
        self.toolbar = self._build_toolbar()
        shell.addWidget(self.toolbar)

        # ---- Vertical splitter: LiveView (top) + Tabs (bottom) ----
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(8)

        # 위: 라이브 뷰 영역
        live_area = self._build_live_area()
        main_splitter.addWidget(live_area)

        # 아래: 4개 작업 탭
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setMovable(False)
        self.tabs.setDocumentMode(False)
        self._build_tabs()
        main_splitter.addWidget(self.tabs)

        # 비율: LiveView 60% / Tabs 40%
        main_splitter.setSizes([520, 360])

        # 콘텐츠 컨테이너 (margin 주기 위함)
        content_wrap = QtWidgets.QWidget()
        content_layout = QtWidgets.QHBoxLayout(content_wrap)
        content_layout.setContentsMargins(14, 10, 14, 10)
        content_layout.addWidget(main_splitter)
        shell.addWidget(content_wrap, 1)

        # ============ Status bar ============
        self.statusBar().showMessage(
            "준비됨  ·  Space: 카메라  ·  B/D/O: 조명  ·  L: ROI 잠금"
        )

        # ============ Controller ============
        self.controller = CaptureController(sense_panel=self.sense_panel)
        self.controller.status.connect(self.statusBar().showMessage)
        self.controller.saved.connect(self._on_saved)
        self.controller.dpc_updated.connect(self._on_dpc_updated)

        # ============ Camera thread ============
        self.cam_thread = QtCore.QThread(self)
        self.cam_worker = CameraWorker(
            cam_index=None, width=1280, height=800, fps=30, gui_emit_fps=15,
        )
        self.cam_worker.moveToThread(self.cam_thread)
        self.cam_worker.frame_ready.connect(self._on_frame)
        self.cam_worker.status.connect(self.statusBar().showMessage)
        self.cam_worker.controls_detected.connect(
            self.camera_panel.update_from_camera
        )
        self.camera_panel.control_changed.connect(self._on_camera_control_changed)
        self.cam_thread.started.connect(self.cam_worker.start)

        # ============ Signals wiring ============
        self.live.roi_changed.connect(self._on_roi)
        # ROI를 데이터셋 패널에도 전달 (라벨링용)
        self.live.roi_changed.connect(self.dataset_panel.set_current_roi)
        # 데이터셋 패널 → 메인 윈도우
        self.dataset_panel.capture_requested.connect(self._on_dataset_capture)
        self.dataset_panel.status_message.connect(self.statusBar().showMessage)
        # 라벨링 박스 변경 → LiveView overlay (📌 점선 박스로 표시)
        self.dataset_panel.pending_changed.connect(
            self.live.set_pending_labels
        )
        # Active learning: AI 검출을 라벨로 추가 요청
        self.dataset_panel.ai_to_labels_requested.connect(
            self._on_dataset_ai_labels
        )

        # 가장 최근 AI 검출 결과 추적 (active learning에서 사용)
        self._last_ai_detections = []

        self.capture_panel.output_dir_changed.connect(self._set_output_dir)
        self.capture_panel.new_seq.connect(self._new_seq)
        self.capture_panel.snap_bf.connect(self._save_bf)
        self.capture_panel.snap_dpcx.connect(self._save_dpcx)
        self.capture_panel.snap_dpcy.connect(self._save_dpcy)
        self.capture_panel.snap_pseudo.connect(self._save_pseudo)
        self.capture_panel.dpc_capture.connect(self._capture_dpc_only)
        self.capture_panel.dpc_capture_and_save_all.connect(
            self._capture_dpc_and_save_all
        )

        self.gallery.image_selected.connect(self._on_gallery_image_clicked)
        self.player.frame_selected.connect(self._load_image_to_preview)

        # ============ AI inference ============
        self._ai_thread = QtCore.QThread(self)
        self._ai_worker = None
        # AIPanel은 DetectPanel 안에 호스팅됨 — 그쪽 시그널 연결
        self.detect_panel.ai_panel.enable_changed.connect(self._on_ai_enable_changed)
        self.detect_panel.ai_panel.model_changed.connect(self._on_ai_model_changed)
        self.detect_panel.ai_panel.conf_changed.connect(self._on_ai_conf_changed)

        # initial output dir sync
        self._set_output_dir(self.capture_panel.ed_out.text().strip())

        # ---- Keyboard shortcuts ----
        self._setup_shortcuts()

    # ============================================================
    # Live area (LiveView 위쪽)
    # ============================================================
    def _build_live_area(self):
        wrap = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        # 헤더 줄: 타이틀 + ROI 정보
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        lbl = QtWidgets.QLabel("실시간 영상")
        lbl.setProperty("role", "title")
        self.lbl_roi_info = QtWidgets.QLabel("관심영역: 없음")
        self.lbl_roi_info.setProperty("role", "muted")
        head.addWidget(lbl)
        head.addWidget(make_separator("v"))
        head.addWidget(self.lbl_roi_info)
        head.addStretch(1)
        col.addLayout(head)

        # LiveView
        self.live = LiveView()
        col.addWidget(self.live, 1)

        # 카메라 시작/정지 (toolbar에도 있지만 이중 안전)
        btnrow = QtWidgets.QHBoxLayout()
        btnrow.setSpacing(8)
        self.btn_start = QtWidgets.QPushButton("카메라 시작")
        self.btn_start.setProperty("role", "primary")
        self.btn_start.setMinimumHeight(30)
        self.btn_start.clicked.connect(self._start_camera)
        self.btn_stop = QtWidgets.QPushButton("정지")
        self.btn_stop.setProperty("role", "danger")
        self.btn_stop.setMinimumHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_camera)
        btnrow.addWidget(self.btn_start, 1)
        btnrow.addWidget(self.btn_stop)
        col.addLayout(btnrow)

        return wrap

    # ============================================================
    # Tabs
    # ============================================================
    def _build_tabs(self):
        # 패널 인스턴스 모두 생성 (시그널 연결을 __init__에서 처리하기 위함)
        self.sense_panel   = SensePanel()
        self.capture_panel = CapturePanel()
        self.camera_panel  = CameraPanel()
        self.dataset_panel = DatasetPanel()
        self.detect_panel  = DetectPanel()

        # AIPanel (DetectPanel 안에 있음) — Hailo 미감지 처리
        if not HAILO_OK:
            self.detect_panel.ai_panel.setEnabled(False)
            self.detect_panel.ai_panel.set_status("Hailo NPU 미감지 — 비활성")

        # Gallery / Player
        self.gallery = GalleryPanel()
        self.player  = PlayerPanel()

        # 4 채널 미리보기 (라이브 탭 안에)
        self.prev_bf     = PreviewView("BF · 명시야")
        self.prev_dpcx   = PreviewView("DPCₓ · 수평")
        self.prev_dpcy   = PreviewView("DPCᵧ · 수직")
        self.prev_pseudo = PreviewView("합성 RGB")
        for prev in (self.prev_bf, self.prev_dpcx,
                     self.prev_dpcy, self.prev_pseudo):
            prev.setMinimumSize(180, 130)

        # ---- 탭 1: 라이브 ----
        live_tab = QtWidgets.QWidget()
        live_layout = QtWidgets.QHBoxLayout(live_tab)
        live_layout.setContentsMargins(8, 8, 8, 8)
        live_layout.setSpacing(10)

        # 좌측: Sense + Capture + Camera 컨트롤 (스크롤)
        controls_inner = QtWidgets.QWidget()
        controls_col = QtWidgets.QVBoxLayout(controls_inner)
        controls_col.setContentsMargins(0, 0, 6, 0)
        controls_col.setSpacing(10)
        controls_col.addWidget(self.sense_panel)
        controls_col.addWidget(self.capture_panel)
        controls_col.addWidget(self.camera_panel)
        controls_col.addStretch(1)

        controls_scroll = QtWidgets.QScrollArea()
        controls_scroll.setWidget(controls_inner)
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        controls_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        controls_scroll.setFixedWidth(440)
        live_layout.addWidget(controls_scroll)

        # 우측: 4 채널 가로 일렬 (DPC 결과 미리보기)
        ch_wrap = QtWidgets.QWidget()
        ch_outer = QtWidgets.QVBoxLayout(ch_wrap)
        ch_outer.setContentsMargins(0, 0, 0, 0)
        ch_outer.setSpacing(8)
        ch_head = QtWidgets.QLabel("DPC 채널 — BF · DPCₓ · DPCᵧ · 합성 RGB")
        ch_head.setProperty("role", "title")
        ch_outer.addWidget(ch_head)

        ch_row = QtWidgets.QHBoxLayout()
        ch_row.setSpacing(8)
        ch_row.addWidget(self.prev_bf, 1)
        ch_row.addWidget(self.prev_dpcx, 1)
        ch_row.addWidget(self.prev_dpcy, 1)
        ch_row.addWidget(self.prev_pseudo, 1)
        ch_outer.addLayout(ch_row, 1)
        live_layout.addWidget(ch_wrap, 1)

        self.tabs.addTab(live_tab, "📷  라이브")

        # ---- 탭 2: 데이터셋 ----
        dataset_tab = QtWidgets.QWidget()
        dataset_layout = QtWidgets.QHBoxLayout(dataset_tab)
        dataset_layout.setContentsMargins(8, 8, 8, 8)
        dataset_layout.setSpacing(10)

        ds_scroll = QtWidgets.QScrollArea()
        ds_scroll.setWidget(self.dataset_panel)
        ds_scroll.setWidgetResizable(True)
        ds_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        ds_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        ds_scroll.setFixedWidth(440)
        dataset_layout.addWidget(ds_scroll)

        # 우측: 도움말 / 워크플로우 안내
        help_card = QtWidgets.QFrame()
        help_card.setProperty("role", "surface")
        help_layout = QtWidgets.QVBoxLayout(help_card)
        help_layout.setContentsMargins(20, 18, 20, 18)
        help_title = QtWidgets.QLabel("📋  라벨링 워크플로우")
        help_title.setProperty("role", "title")
        help_layout.addWidget(help_title)
        help_text = QtWidgets.QLabel(
            "1. 라이브뷰에서 분열기를 발견하면 마우스로 ROI를 드래그합니다.\n\n"
            "2. 좌측 패널에서 알맞은 클래스(전기/중기/후기/말기 등)를 선택합니다.\n\n"
            "3. ‘박스 추가’ 버튼으로 현재 ROI를 라벨로 누적합니다.\n"
            "   같은 프레임에서 여러 박스를 추가할 수 있습니다.\n\n"
            "4. ‘스냅샷 + 라벨 저장’ 버튼으로 이미지 + COCO 라벨을 저장합니다.\n\n"
            "5. 충분히 모았으면(클래스당 30+장 권장) ‘YOLO 형식으로 export’로\n"
            "   Ultralytics 학습용 폴더를 생성합니다.\n\n"
            "💡 Ctrl+L: ROI 잠금 / Space: 카메라 / B,D,O: 조명 단축키"
        )
        help_text.setProperty("role", "muted")
        help_text.setWordWrap(True)
        help_layout.addWidget(help_text)
        help_layout.addStretch(1)
        dataset_layout.addWidget(help_card, 1)

        self.tabs.addTab(dataset_tab, "🏷️  데이터셋")

        # ---- 탭 3: 검출 ----
        detect_tab = QtWidgets.QWidget()
        detect_layout = QtWidgets.QHBoxLayout(detect_tab)
        detect_layout.setContentsMargins(8, 8, 8, 8)
        detect_layout.setSpacing(10)

        det_scroll = QtWidgets.QScrollArea()
        det_scroll.setWidget(self.detect_panel)
        det_scroll.setWidgetResizable(True)
        det_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        det_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        det_scroll.setFixedWidth(440)
        detect_layout.addWidget(det_scroll)

        # 우측: 양파 분열 단계 가이드
        guide_card = QtWidgets.QFrame()
        guide_card.setProperty("role", "surface")
        guide_layout = QtWidgets.QVBoxLayout(guide_card)
        guide_layout.setContentsMargins(20, 18, 20, 18)
        guide_title = QtWidgets.QLabel("🔬  양파 체세포 분열 단계")
        guide_title.setProperty("role", "title")
        guide_layout.addWidget(guide_title)
        guide_text = QtWidgets.QLabel(
            "• 간기 (Interphase) — 분열 전, 핵 안에 염색사 산재\n\n"
            "• 전기 (Prophase) — 염색사 응축, 핵막 사라짐\n\n"
            "• 중기 (Metaphase) — 염색체가 적도판에 정렬 ⭐ 가장 보기 좋음\n\n"
            "• 후기 (Anaphase) — 염색분체 양극 분리\n\n"
            "• 말기 (Telophase) — 두 딸세포로 분리, 핵막 재형성\n\n"
            "──────────\n"
            "현재 사전 학습 모델은 COCO 80 클래스(사람·동물 등)이라\n"
            "분열기를 못 잡습니다. 데이터셋 탭에서 라벨링 후 학습한\n"
            "사용자 모델을 선택하면 자동 검출 가능합니다."
        )
        guide_text.setProperty("role", "muted")
        guide_text.setWordWrap(True)
        guide_layout.addWidget(guide_text)
        guide_layout.addStretch(1)
        detect_layout.addWidget(guide_card, 1)

        self.tabs.addTab(detect_tab, "🤖  검출")

        # ---- 탭 4: 아카이브 ----
        archive_tab = QtWidgets.QWidget()
        archive_layout = QtWidgets.QVBoxLayout(archive_tab)
        archive_layout.setContentsMargins(8, 8, 8, 8)
        archive_layout.setSpacing(8)

        archive_tabs = QtWidgets.QTabWidget()
        archive_tabs.addTab(self.gallery, "갤러리")
        archive_tabs.addTab(self.player, "플레이어")
        self.archive_tabs = archive_tabs
        archive_layout.addWidget(archive_tabs)

        self.tabs.addTab(archive_tab, "📁  아카이브")

    # ============================================================
    # Toolbar
    # ============================================================
    def _build_toolbar(self):
        tb = QtWidgets.QFrame()
        tb.setProperty("role", "toolbar")
        tb.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        tb.setFixedHeight(52)

        layout = QtWidgets.QHBoxLayout(tb)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(6)

        self.btn_tb_cam = QtWidgets.QPushButton("▶  카메라 시작")
        self.btn_tb_cam.setProperty("role", "primary")
        self.btn_tb_cam.setMinimumHeight(36)
        self.btn_tb_cam.clicked.connect(self._toggle_camera_quick)
        layout.addWidget(self.btn_tb_cam)

        layout.addSpacing(8)
        layout.addWidget(make_separator("v"))
        layout.addSpacing(8)

        for label, key, role in [("BF", "BF", None),
                                   ("DF", "DF", None),
                                   ("끔", "OFF", "danger")]:
            btn = QtWidgets.QPushButton(label)
            btn.setMinimumHeight(36)
            btn.setFixedWidth(56)
            if role:
                btn.setProperty("role", role)
            btn.clicked.connect(
                lambda _c=False, k=key: self.sense_panel.apply_preset(k)
            )
            layout.addWidget(btn)

        layout.addSpacing(8)
        layout.addWidget(make_separator("v"))
        layout.addSpacing(8)

        btn_dpc = QtWidgets.QPushButton("📸  DPC 촬영")
        btn_dpc.setProperty("role", "primary")
        btn_dpc.setMinimumHeight(36)
        btn_dpc.clicked.connect(self._capture_dpc_only)
        layout.addWidget(btn_dpc)

        btn_dpc_all = QtWidgets.QPushButton("💾  촬영 + 전체 저장")
        btn_dpc_all.setProperty("role", "success")
        btn_dpc_all.setMinimumHeight(36)
        btn_dpc_all.clicked.connect(self._capture_dpc_and_save_all)
        layout.addWidget(btn_dpc_all)

        layout.addStretch(1)

        self.btn_roi_lock = QtWidgets.QPushButton("🔓  ROI 자유")
        self.btn_roi_lock.setCheckable(True)
        self.btn_roi_lock.setMinimumHeight(36)
        self.btn_roi_lock.toggled.connect(self._on_roi_lock_toggle)
        layout.addWidget(self.btn_roi_lock)

        return tb

    def _toggle_camera_quick(self):
        if self.cam_thread.isRunning():
            self._stop_camera()
            self.btn_tb_cam.setText("▶  카메라 시작")
            self.btn_tb_cam.setProperty("role", "primary")
        else:
            self._start_camera()
            self.btn_tb_cam.setText("⏸  카메라 정지")
            self.btn_tb_cam.setProperty("role", "danger")
        self.btn_tb_cam.style().unpolish(self.btn_tb_cam)
        self.btn_tb_cam.style().polish(self.btn_tb_cam)

    def _on_roi_lock_toggle(self, locked):
        self.live.set_roi_locked(locked)
        if locked:
            self.btn_roi_lock.setText("🔒  ROI 잠김")
            self.statusBar().showMessage("ROI 잠금됨 — 드래그/우클릭 무효", 3000)
        else:
            self.btn_roi_lock.setText("🔓  ROI 자유")
            self.statusBar().showMessage("ROI 잠금 해제", 2000)

    # ============================================================
    # Shortcuts
    # ============================================================
    def _setup_shortcuts(self):
        sc = lambda key, fn: QtWidgets.QShortcut(
            QtGui.QKeySequence(key), self, activated=fn
        )
        sc("Space",         self._toggle_camera_quick)
        sc("B",             lambda: self.sense_panel.apply_preset("BF"))
        sc("D",             lambda: self.sense_panel.apply_preset("DF"))
        sc("O",             lambda: self.sense_panel.apply_preset("OFF"))
        sc("L",             lambda: self.btn_roi_lock.toggle())
        sc("Ctrl+Shift+S",  self._capture_dpc_and_save_all)
        sc("Ctrl+D",        self._capture_dpc_only)
        # 탭 단축키
        sc("Ctrl+1",        lambda: self.tabs.setCurrentIndex(0))  # 라이브
        sc("Ctrl+2",        lambda: self.tabs.setCurrentIndex(1))  # 데이터셋
        sc("Ctrl+3",        lambda: self.tabs.setCurrentIndex(2))  # 검출
        sc("Ctrl+4",        lambda: self.tabs.setCurrentIndex(3))  # 아카이브

    # ============================================================
    # Camera
    # ============================================================
    def _start_camera(self):
        if not self.cam_thread.isRunning():
            self.cam_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.header.set_camera_active(True)

    def _stop_camera(self):
        self.cam_worker.stop()
        self.cam_thread.quit()
        self.cam_thread.wait(1000)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.header.set_camera_active(False)
        self.camera_panel.reset_to_no_camera()

    def _on_camera_control_changed(self, name, value):
        QtCore.QMetaObject.invokeMethod(
            self.cam_worker, "set_v4l2_control",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, name),
            QtCore.Q_ARG(int, int(value)),
        )

    def _on_frame(self, frame_bgr):
        self._last_frame = frame_bgr
        self.live.set_frame(frame_bgr)
        self.controller.on_frame(frame_bgr)
        if self._ai_worker is not None:
            self._ai_worker.feed_frame(frame_bgr)

    # ============================================================
    # ROI
    # ============================================================
    def _on_roi(self, roi_xywh):
        self._roi = roi_xywh
        self.controller.update_roi(roi_xywh)
        if roi_xywh:
            x, y, w, h = roi_xywh
            self.lbl_roi_info.setText(
                "관심영역: x=%d y=%d  %d×%d  ·  우클릭으로 해제" % (x, y, w, h)
            )
            self.statusBar().showMessage("관심영역 설정됨: %s" % str(roi_xywh))
        else:
            self.lbl_roi_info.setText("관심영역: 없음")
            self.statusBar().showMessage("관심영역 해제됨")

    # ============================================================
    # Output / sequence
    # ============================================================
    def _set_output_dir(self, path: str):
        path = path.strip()
        if not path:
            return
        self.controller.set_output_dir(path)
        self.gallery.set_output_dir(path)

    def _new_seq(self, name: str):
        self.controller.new_sequence(name)
        self.gallery.refresh()

    # ============================================================
    # Snapshot saves
    # ============================================================
    def _save_bf(self):
        if self.controller.bf_u8 is None:
            self.statusBar().showMessage("BF 준비되지 않음. 먼저 'DPC 촬영'을 실행하세요.")
            return
        self.controller.save_snapshot("BF", self.controller.bf_u8)

    def _save_dpcx(self):
        if self.controller.dpcx_u8 is None:
            self.statusBar().showMessage("DPCx 준비되지 않음. 먼저 'DPC 촬영'을 실행하세요.")
            return
        self.controller.save_snapshot("DPCx", self.controller.dpcx_u8)

    def _save_dpcy(self):
        if self.controller.dpcy_u8 is None:
            self.statusBar().showMessage("DPCy 준비되지 않음. 먼저 'DPC 촬영'을 실행하세요.")
            return
        self.controller.save_snapshot("DPCy", self.controller.dpcy_u8)

    def _save_pseudo(self):
        if self.controller.pseudo_bgr is None:
            self.statusBar().showMessage("합성RGB 준비되지 않음. 먼저 'DPC 촬영'을 실행하세요.")
            return
        self.controller.save_snapshot("pseudoRGB", self.controller.pseudo_bgr)

    # ============================================================
    # DPC capture
    # ============================================================
    def _capture_dpc_only(self):
        self._pending_save_all = False
        self.header.set_capturing()
        self.controller.start_dpc_capture(include_bf=True)

    def _capture_dpc_and_save_all(self):
        self._pending_save_all = True
        self.header.set_capturing()
        self.controller.start_dpc_capture(include_bf=True)

    def _on_dpc_updated(self, pack: dict):
        bf = pack.get("bf_u8")
        dx = pack.get("dpcx_u8")
        dy = pack.get("dpcy_u8")
        prgb = pack.get("pseudo_bgr")

        if bf is not None:
            self.prev_bf.set_gray_u8(bf)
        if dx is not None:
            self.prev_dpcx.set_gray_u8(dx)
        if dy is not None:
            self.prev_dpcy.set_gray_u8(dy)
        if prgb is not None:
            self.prev_pseudo.set_bgr(prgb)

        if self._pending_save_all:
            self._pending_save_all = False
            if bf is not None:
                self.controller.save_snapshot("BF", bf)
            if dx is not None:
                self.controller.save_snapshot("DPCx", dx)
            if dy is not None:
                self.controller.save_snapshot("DPCy", dy)
            if prgb is not None:
                self.controller.save_snapshot("pseudoRGB", prgb)

        self.header.set_camera_active(self.cam_thread.isRunning())

    # ============================================================
    # Gallery / Player
    # ============================================================
    def _on_saved(self, path: str):
        self.gallery.refresh()

    def _on_gallery_image_clicked(self, path: str):
        if not path or not os.path.isfile(path):
            return
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            self.statusBar().showMessage("이미지를 불러올 수 없습니다: %s" % path)
            return
        if img.ndim == 2:
            img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            img_bgr = img
        self._route_image_to_channel(path, img_bgr)
        self.statusBar().showMessage("불러옴: %s" % path)

        seq_dir = guess_seq_dir_from_image(path)
        if seq_dir:
            self.player.load_sequence(seq_dir)
            self.archive_tabs.setCurrentWidget(self.player)

        self._show_image_popup(path, prefetched_bgr=img_bgr)

    def _show_image_popup(self, path: str, prefetched_bgr=None):
        if not path or not os.path.isfile(path):
            return
        dlg = ImageViewerDialog(path, self, prefetched_bgr=prefetched_bgr)
        dlg.exec_()

    def _load_image_to_preview(self, path: str):
        if not path or not os.path.isfile(path):
            return
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return
        if img.ndim == 2:
            img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            img_bgr = img
        self._route_image_to_channel(path, img_bgr)

    def _route_image_to_channel(self, path: str, img_bgr):
        name = os.path.basename(path).lower()
        if "dpcx" in name:
            self.prev_dpcx.set_bgr(img_bgr)
        elif "dpcy" in name:
            self.prev_dpcy.set_bgr(img_bgr)
        elif "pseudo" in name or "rgb" in name:
            self.prev_pseudo.set_bgr(img_bgr)
        else:
            self.prev_bf.set_bgr(img_bgr)

    # ============================================================
    # Dataset tab — 캡처 요청
    # ============================================================
    def _on_dataset_capture(self):
        """DatasetPanel이 현재 frame 요청 → 우리가 _last_frame 전달."""
        if self._last_frame is None:
            self.statusBar().showMessage(
                "데이터셋 저장 실패: 카메라가 시작되지 않았습니다"
            )
            return
        self.dataset_panel.receive_capture_frame(self._last_frame.copy())

    # ============================================================
    # AI inference
    # ============================================================
    def _on_ai_enable_changed(self, on: bool):
        if on:
            hef = self.detect_panel.ai_panel.current_model_path()
            if not hef:
                self.statusBar().showMessage("AI: 사용 가능한 모델이 없습니다")
                self.detect_panel.ai_panel.btn_enable.setChecked(False)
                return
            self._start_ai_worker(hef)
        else:
            self._stop_ai_worker()

    def _on_ai_model_changed(self, hef_path: str):
        if self._ai_worker is not None and self.detect_panel.ai_panel.is_enabled():
            self._stop_ai_worker()
            if hef_path:
                self._start_ai_worker(hef_path)

    def _on_ai_conf_changed(self, conf: float):
        if self._ai_worker is not None:
            QtCore.QMetaObject.invokeMethod(
                self._ai_worker, "set_conf_threshold",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(float, conf),
            )

    def _start_ai_worker(self, hef_path: str):
        if self._ai_worker is not None:
            return
        if not self._ai_thread.isRunning():
            self._ai_thread.start()
        self._ai_worker = InferenceWorker(
            hef_path,
            conf_threshold=self.detect_panel.ai_panel.sld_conf.value() / 100.0,
        )
        self._ai_worker.moveToThread(self._ai_thread)
        # 검출 결과 → LiveView overlay + DetectPanel 통계
        self._ai_worker.detections_ready.connect(self._on_ai_detections)
        self._ai_worker.detections_ready.connect(
            self.detect_panel.update_detections
        )
        self._ai_worker.fps_updated.connect(self.detect_panel.ai_panel.set_fps)
        self._ai_worker.status.connect(self.detect_panel.ai_panel.set_status)
        QtCore.QMetaObject.invokeMethod(
            self._ai_worker, "start", QtCore.Qt.QueuedConnection
        )

    def _stop_ai_worker(self):
        if self._ai_worker is None:
            return
        QtCore.QMetaObject.invokeMethod(
            self._ai_worker, "stop", QtCore.Qt.BlockingQueuedConnection
        )
        try:
            self._ai_worker.detections_ready.disconnect()
            self._ai_worker.fps_updated.disconnect()
            self._ai_worker.status.disconnect()
        except Exception:
            pass
        self._ai_worker.deleteLater()
        self._ai_worker = None
        self.live.clear_detections()
        self.detect_panel.ai_panel.set_detection_count(0)

    def _on_ai_detections(self, detections):
        # 최근 검출 결과 캐시 (active learning에서 사용)
        self._last_ai_detections = list(detections) if detections else []
        self.live.set_detections(detections)
        self.detect_panel.ai_panel.set_detection_count(len(detections))

    def _on_dataset_ai_labels(self):
        """DatasetPanel이 AI 검출 결과를 라벨로 요청 → 캐시된 검출 전달."""
        if self._ai_worker is None:
            self.statusBar().showMessage(
                "AI 추론 비활성 — 검출 탭에서 먼저 활성화하세요"
            )
            return
        self.dataset_panel.receive_ai_detections(self._last_ai_detections)

    # ============================================================
    # Close
    # ============================================================
    def closeEvent(self, ev):
        try:
            self._stop_ai_worker()
        except Exception:
            pass
        try:
            self._ai_thread.quit()
            self._ai_thread.wait(1000)
        except Exception:
            pass
        try:
            self._stop_camera()
        except Exception:
            pass
        try:
            self.sense_panel.clear()
        except Exception:
            pass
        ev.accept()
