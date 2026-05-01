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
from ..util.image_convert import crop_bgr

from .live_view import LiveView
from .preview import PreviewView
from .sense_panel import SensePanel
from .capture_panel import CapturePanel
from .camera_panel import CameraPanel
from .gallery_panel import GalleryPanel
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

        # ---- 두 QStackedWidget: 좌측 메뉴(컨트롤) / 하단 보조 콘텐츠 ----
        # menu_stack : LiveView 좌측에 — 탭별 컨트롤 슬라이더/패널
        # aux_stack  : 화면 하단에 — 탭별 보조 콘텐츠 (DPC 채널 / 가이드)
        self.menu_stack = QtWidgets.QStackedWidget()
        self.aux_stack  = QtWidgets.QStackedWidget()
        self._build_panels()  # 4 탭 × (menu page + aux page)

        # 상단: 좌(메뉴 컨트롤) + 우(LiveView 큼)
        live_area = self._build_live_area()
        top_h = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        top_h.setChildrenCollapsible(False)
        top_h.setHandleWidth(8)
        top_h.addWidget(self.menu_stack)
        top_h.addWidget(live_area)
        top_h.setSizes([400, 1000])  # 메뉴 좁게, 카메라 넓게

        # 일반 모드 페이지: 상단(메뉴+LiveView) + 하단(보조)
        normal_split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        normal_split.setChildrenCollapsible(False)
        normal_split.setHandleWidth(8)
        normal_split.addWidget(top_h)
        normal_split.addWidget(self.aux_stack)
        normal_split.setSizes([620, 260])

        # 아카이브 풀스크린 페이지: 갤러리만 (시퀀스 플레이어 제거됨)
        archive_page = QtWidgets.QWidget()
        archive_layout = QtWidgets.QVBoxLayout(archive_page)
        archive_layout.setContentsMargins(0, 0, 0, 0)
        archive_layout.addWidget(self.gallery)

        # 메인 stack: 일반 모드 ↔ 아카이브 풀스크린 모드 전환
        self.main_stack = QtWidgets.QStackedWidget()
        self.main_stack.addWidget(normal_split)   # idx 0 — 라이브/데이터셋/검출
        self.main_stack.addWidget(archive_page)   # idx 1 — 아카이브 (갤러리 풀스크린)

        # 좌측 사이드바 (수직 탭 버튼)
        sidebar = self._build_sidebar()

        # 콘텐츠 컨테이너 — sidebar + main_stack
        content_wrap = QtWidgets.QWidget()
        content_layout = QtWidgets.QHBoxLayout(content_wrap)
        content_layout.setContentsMargins(0, 0, 14, 10)
        content_layout.setSpacing(10)
        content_layout.addWidget(sidebar)
        content_layout.addWidget(self.main_stack, 1)
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
        # 🔆 고배율 부스트 — sense_panel 버튼 → 카메라 노출/게인 부스트
        self.sense_panel.hi_mag_requested.connect(
            self.cam_worker.apply_hi_mag_boost,
            QtCore.Qt.QueuedConnection,
        )
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

        # LiveView 먼저 생성 (헤더 줄에서 시그널 연결)
        self.live = LiveView()

        # 헤더 줄: 타이틀 + ROI 정보 + 줌 컨트롤
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

        # 줌 컨트롤
        self.btn_zoom_out = QtWidgets.QPushButton("－")
        self.btn_zoom_out.setProperty("role", "ghost")
        self.btn_zoom_out.setFixedWidth(36)
        self.btn_zoom_out.setToolTip("축소 (Ctrl+휠 / Ctrl+−)")
        self.lbl_zoom = QtWidgets.QLabel("100%")
        self.lbl_zoom.setProperty("role", "value")
        self.lbl_zoom.setMinimumWidth(56)
        self.lbl_zoom.setAlignment(QtCore.Qt.AlignCenter)
        self.btn_zoom_in = QtWidgets.QPushButton("＋")
        self.btn_zoom_in.setProperty("role", "ghost")
        self.btn_zoom_in.setFixedWidth(36)
        self.btn_zoom_in.setToolTip("확대 (Ctrl+휠 / Ctrl+=)")
        self.btn_zoom_reset = QtWidgets.QPushButton("Fit")
        self.btn_zoom_reset.setProperty("role", "ghost")
        self.btn_zoom_reset.setFixedWidth(48)
        self.btn_zoom_reset.setToolTip("원래 크기로 (Ctrl+0)")
        head.addWidget(self.btn_zoom_out)
        head.addWidget(self.lbl_zoom)
        head.addWidget(self.btn_zoom_in)
        head.addWidget(self.btn_zoom_reset)
        col.addLayout(head)

        # 줌 시그널 연결
        self.btn_zoom_in.clicked.connect(lambda: self.live.zoom_by(1.25))
        self.btn_zoom_out.clicked.connect(lambda: self.live.zoom_by(1.0 / 1.25))
        self.btn_zoom_reset.clicked.connect(self.live.reset_zoom)
        self.live.zoom_changed.connect(self._on_live_zoom_changed)

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
    # Panels — 각 탭을 (메뉴 컨트롤 / 보조 콘텐츠) 두 페이지로 분리.
    # menu_stack 은 LiveView 좌측에, aux_stack 은 화면 하단에 배치된다.
    # ============================================================
    def _build_panels(self):
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

        # Gallery (시퀀스 플레이어는 제거됨)
        self.gallery = GalleryPanel()

        # 4 채널 미리보기 (하단 보조 영역 — 작게 가로 일렬)
        self.prev_bf     = PreviewView("BF · 명시야")
        self.prev_dpcx   = PreviewView("DPCₓ · 수평")
        self.prev_dpcy   = PreviewView("DPCᵧ · 수직")
        self.prev_pseudo = PreviewView("합성 RGB")
        for prev in (self.prev_bf, self.prev_dpcx,
                     self.prev_dpcy, self.prev_pseudo):
            prev.setMinimumSize(150, 110)
            prev.setMaximumHeight(220)

        # ---- 페이지 1: 라이브 ----
        # 메뉴 (좌측 상단): Sense + Capture + Camera 슬라이더 스크롤
        live_menu = self._wrap_scroll([
            self.sense_panel, self.capture_panel, self.camera_panel
        ])
        # 보조 (하단): DPC 4채널 가로 일렬 (작게)
        live_aux = QtWidgets.QWidget()
        live_aux_col = QtWidgets.QVBoxLayout(live_aux)
        live_aux_col.setContentsMargins(8, 4, 8, 8)
        live_aux_col.setSpacing(6)
        ch_head = QtWidgets.QLabel("DPC 채널 — BF · DPCₓ · DPCᵧ · 합성 RGB")
        ch_head.setProperty("role", "title")
        live_aux_col.addWidget(ch_head)
        ch_row = QtWidgets.QHBoxLayout()
        ch_row.setSpacing(8)
        ch_row.addWidget(self.prev_bf, 1)
        ch_row.addWidget(self.prev_dpcx, 1)
        ch_row.addWidget(self.prev_dpcy, 1)
        ch_row.addWidget(self.prev_pseudo, 1)
        live_aux_col.addLayout(ch_row, 1)
        self.menu_stack.addWidget(live_menu)
        self.aux_stack.addWidget(live_aux)

        # ---- 페이지 2: 데이터셋 ----
        # 메뉴: dataset_panel (클래스 선택 + ROI + 라벨 누적)
        ds_menu = QtWidgets.QScrollArea()
        ds_menu.setWidget(self.dataset_panel)
        ds_menu.setWidgetResizable(True)
        ds_menu.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        ds_menu.setFrameShape(QtWidgets.QFrame.NoFrame)
        # 보조 (하단): 라벨링 워크플로우 가이드 카드
        ds_aux = self._make_card(
            "📋  라벨링 워크플로우",
            "1. 라이브뷰에서 분열기를 발견하면 마우스로 ROI를 드래그   "
            "2. 좌측 패널에서 클래스(전기/중기/후기/말기 등) 선택   "
            "3. ‘박스 추가’로 현재 ROI를 라벨로 누적   "
            "4. ‘스냅샷 + 라벨 저장’으로 이미지 + COCO 저장   "
            "5. 클래스당 30+장 모이면 ‘YOLO 형식 export’로 학습 폴더 생성   "
            "💡 Ctrl+L: ROI 잠금 · Space: 카메라 · B/D/O: 조명"
        )
        self.menu_stack.addWidget(ds_menu)
        self.aux_stack.addWidget(ds_aux)

        # ---- 페이지 3: 검출 ----
        # 메뉴: detect_panel (AI 추론 컨트롤 + 클래스 카운트)
        det_menu = QtWidgets.QScrollArea()
        det_menu.setWidget(self.detect_panel)
        det_menu.setWidgetResizable(True)
        det_menu.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        det_menu.setFrameShape(QtWidgets.QFrame.NoFrame)
        # 보조 (하단): 분열 단계 가이드 카드
        det_aux = self._make_card(
            "🔬  양파 체세포 분열 단계",
            "• 간기 (Interphase) — 분열 전, 핵 안에 염색사 산재   "
            "• 전기 (Prophase) — 염색사 응축, 핵막 사라짐   "
            "• 중기 (Metaphase) — 염색체가 적도판에 정렬 ⭐ 가장 보기 좋음   "
            "• 후기 (Anaphase) — 염색분체 양극 분리   "
            "• 말기 (Telophase) — 두 딸세포로 분리, 핵막 재형성   "
            "ℹ️ 사전 모델(COCO 80)은 분열기 미지원 — 데이터셋 탭에서 라벨링→학습 후 사용자 모델 선택 시 자동 검출."
        )
        self.menu_stack.addWidget(det_menu)
        self.aux_stack.addWidget(det_aux)

        # ---- 페이지 4: 아카이브 ----
        # 갤러리/플레이어는 main_stack 의 archive_split (풀스크린)에서 직접
        # 표시되므로 여기엔 placeholder 만 추가 (인덱스 정합성용 — 실제로는
        # main_stack 이 archive page 로 전환되어 보이지 않음).
        self.menu_stack.addWidget(QtWidgets.QWidget())
        self.aux_stack.addWidget(QtWidgets.QWidget())

    def _wrap_scroll(self, widgets):
        inner = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(inner)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(10)
        for w in widgets:
            col.addWidget(w)
        col.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        return scroll

    def _make_card(self, title: str, body: str) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setProperty("role", "surface")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setProperty("role", "title")
        layout.addWidget(title_lbl)
        body_lbl = QtWidgets.QLabel(body)
        body_lbl.setProperty("role", "muted")
        body_lbl.setWordWrap(True)
        layout.addWidget(body_lbl)
        layout.addStretch(1)
        return card

    # ============================================================
    # Sidebar (좌측 수직 탭 — 4개 작업 탭 선택)
    # ============================================================
    def _build_sidebar(self):
        sidebar = QtWidgets.QFrame()
        sidebar.setProperty("role", "sidebar")
        sidebar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        sidebar.setFixedWidth(96)

        col = QtWidgets.QVBoxLayout(sidebar)
        col.setContentsMargins(8, 14, 8, 14)
        col.setSpacing(6)

        items = [
            ("📷", "라이브"),
            ("🏷️", "데이터셋"),
            ("🤖", "검출"),
            ("📁", "아카이브"),
        ]
        self._sidebar_btns = []
        for i, (icon, name) in enumerate(items):
            btn = QtWidgets.QToolButton()
            btn.setText(f"{icon}\n{name}")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setProperty("role", "sidebarTab")
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            btn.setMinimumHeight(64)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                              QtWidgets.QSizePolicy.Fixed)
            btn.clicked.connect(
                lambda _c=False, idx=i: self._select_tab(idx)
            )
            col.addWidget(btn)
            self._sidebar_btns.append(btn)

        self._sidebar_btns[0].setChecked(True)
        col.addStretch(1)
        return sidebar

    def _select_tab(self, idx: int):
        """사이드바 버튼 → 메인 모드(일반/아카이브) + menu/aux stack 동기화."""
        if idx == 3:
            # 아카이브: 갤러리 + 플레이어 풀스크린
            self.main_stack.setCurrentIndex(1)
        else:
            # 라이브 / 데이터셋 / 검출: 일반 모드
            self.main_stack.setCurrentIndex(0)
            self.menu_stack.setCurrentIndex(idx)
            self.aux_stack.setCurrentIndex(idx)
        if 0 <= idx < len(self._sidebar_btns):
            self._sidebar_btns[idx].setChecked(True)

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

    def _on_live_zoom_changed(self, z: float):
        if abs(z - 1.0) < 0.01:
            self.lbl_zoom.setText("Fit")
        else:
            self.lbl_zoom.setText("%d%%" % int(round(z * 100)))

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
        # 탭 단축키 (사이드바 버튼도 동기화)
        sc("Ctrl+1",        lambda: self._select_tab(0))  # 라이브
        sc("Ctrl+2",        lambda: self._select_tab(1))  # 데이터셋
        sc("Ctrl+3",        lambda: self._select_tab(2))  # 검출
        sc("Ctrl+4",        lambda: self._select_tab(3))  # 아카이브
        # LiveView 줌 단축키
        sc("Ctrl+0",        self.live.reset_zoom)
        sc("Ctrl+=",        lambda: self.live.zoom_by(1.25))
        sc("Ctrl++",        lambda: self.live.zoom_by(1.25))
        sc("Ctrl+-",        lambda: self.live.zoom_by(1.0 / 1.25))

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

        # 시퀀스 플레이어가 제거되었으므로 시퀀스 자동 로드는 하지 않는다.
        self._show_image_popup(path, prefetched_bgr=img_bgr)

    def _show_image_popup(self, path: str, prefetched_bgr=None):
        if not path or not os.path.isfile(path):
            return
        # 갤러리 현재 이미지 목록을 같이 넘겨 ←/→ 네비게이션 가능하게 함
        image_list = []
        try:
            for i in range(self.gallery.listw.count()):
                p = self.gallery.listw.item(i).data(QtCore.Qt.UserRole)
                if p:
                    image_list.append(p)
        except Exception:
            image_list = [path]
        dlg = ImageViewerDialog(
            path, self, prefetched_bgr=prefetched_bgr,
            image_list=image_list or [path],
        )
        dlg.exec_()

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
