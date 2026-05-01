# app/ui/ai_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIPanel — UI controls for Hailo NPU inference.
"""

import os
import glob

from PyQt5 import QtCore, QtWidgets

from .style import Color, make_separator


# Pre-installed Hailo models
HAILO_MODELS_DIR = "/usr/share/hailo-models"
DEFAULT_MODEL_NAME = "yolov11m_h10.hef"

# Custom user models — drop additional .hef files here
USER_MODELS_DIR = os.path.expanduser("~/RAIM_OUTPUT/models")

# 우리 HailoYOLOInference wrapper는 NMS 내장 detection 모델만 처리.
# 다음 키워드가 이름에 포함된 모델은 별도 후처리가 필요해 제외:
INCOMPATIBLE_KEYWORDS = (
    "seg",        # segmentation (mask coefficient 별도 처리 필요)
    "pose",       # pose estimation (keypoint decode 필요)
    "depth",      # depth estimation
    "scrfd",      # face detection (다른 NMS 형식)
    "resnet",     # classification
    "efficientnet",
    "_h8.hef",    # H10 디바이스에서 부동작
    "_h8l",
    "_h8l_mz",
)


def is_compatible_model(filename: str) -> bool:
    """우리 wrapper로 처리 가능한 모델인지 판정."""
    name = filename.lower()
    return not any(k in name for k in INCOMPATIBLE_KEYWORDS)


class AIPanel(QtWidgets.QGroupBox):
    """AI 추론 패널 — 모델 선택 + 활성화 + 신뢰도 + 상태 표시."""

    enable_changed = QtCore.pyqtSignal(bool)
    model_changed  = QtCore.pyqtSignal(str)   # absolute HEF path
    conf_changed   = QtCore.pyqtSignal(float) # 0.0~1.0

    def __init__(self, parent=None):
        super().__init__("AI 추론  ·  HAILO-10H", parent)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        # ---- enable toggle ----
        self.btn_enable = QtWidgets.QPushButton("AI 추론 활성화")
        self.btn_enable.setProperty("role", "primary")
        self.btn_enable.setCheckable(True)
        self.btn_enable.setMinimumHeight(34)
        self.btn_enable.toggled.connect(self._on_toggle)
        root.addWidget(self.btn_enable)

        # ---- model selection ----
        cap_m = QtWidgets.QLabel("모델 (.hef)")
        cap_m.setProperty("role", "caption")
        root.addWidget(cap_m)

        self.cmb_model = QtWidgets.QComboBox()
        self._populate_models()
        self.cmb_model.currentIndexChanged.connect(self._on_model_change)
        root.addWidget(self.cmb_model)

        # ---- confidence threshold ----
        cap_c = QtWidgets.QLabel("신뢰도 임계값")
        cap_c.setProperty("role", "caption")
        root.addWidget(cap_c)

        c_row = QtWidgets.QHBoxLayout()
        c_row.setSpacing(8)
        self.sld_conf = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_conf.setRange(5, 95)
        self.sld_conf.setValue(25)
        self.sld_conf.setSingleStep(1)
        self.sld_conf.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.sld_conf.setTickInterval(10)
        self.lbl_conf = QtWidgets.QLabel("0.25")
        self.lbl_conf.setProperty("role", "value")
        self.lbl_conf.setFixedWidth(40)
        self.lbl_conf.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        # debounce: live label only, emit on slider release
        self.sld_conf.valueChanged.connect(self._on_conf_value_changed)
        self.sld_conf.sliderReleased.connect(self._on_conf_released)
        c_row.addWidget(self.sld_conf, 1)
        c_row.addWidget(self.lbl_conf)
        root.addLayout(c_row)

        root.addWidget(make_separator("h"))

        # ---- status block ----
        self.lbl_status = QtWidgets.QLabel("대기 — 모델 선택 후 활성화")
        self.lbl_status.setProperty("role", "muted")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        s_row = QtWidgets.QHBoxLayout()
        s_row.setSpacing(8)
        cap_fps = QtWidgets.QLabel("FPS")
        cap_fps.setProperty("role", "caption")
        self.lbl_fps = QtWidgets.QLabel("—")
        self.lbl_fps.setProperty("role", "value")
        self.lbl_fps.setFixedWidth(48)

        cap_n = QtWidgets.QLabel("검출")
        cap_n.setProperty("role", "caption")
        self.lbl_count = QtWidgets.QLabel("0")
        self.lbl_count.setProperty("role", "value")
        self.lbl_count.setFixedWidth(36)

        s_row.addWidget(cap_fps)
        s_row.addWidget(self.lbl_fps)
        s_row.addStretch(1)
        s_row.addWidget(cap_n)
        s_row.addWidget(self.lbl_count)
        root.addLayout(s_row)

    # ---------- model catalog ----------
    def _populate_models(self):
        # 1) Pre-installed h10 detection models — NMS 내장이라 우리가 디코드 가능
        all_h10 = sorted(glob.glob(os.path.join(HAILO_MODELS_DIR, "*_h10.hef")))
        models = [p for p in all_h10 if is_compatible_model(os.path.basename(p))]

        # 2) Custom user models — 사용자가 직접 학습 후 변환한 .hef
        if os.path.isdir(USER_MODELS_DIR):
            models += sorted(glob.glob(os.path.join(USER_MODELS_DIR, "*.hef")))

        for path in models:
            name = os.path.basename(path)
            tag = "  ·  사용자" if path.startswith(USER_MODELS_DIR) else ""
            display = name + tag
            self.cmb_model.addItem(display, userData=path)

        # 호환 안 되는 모델은 회색으로 (선택은 안 됨)
        skipped = [p for p in all_h10 if not is_compatible_model(os.path.basename(p))]
        for path in skipped:
            name = os.path.basename(path)
            self.cmb_model.addItem(name + "  ·  미지원 (seg/pose/cls)",
                                   userData="")
            # 마지막 추가된 항목을 disabled로
            i = self.cmb_model.count() - 1
            model = self.cmb_model.model()
            item = model.item(i)
            if item is not None:
                item.setEnabled(False)

        if not models:
            self.cmb_model.insertItem(0, "(호환 모델 없음 — 사용자 모델 추가 필요)",
                                       userData="")

        # 기본 선택
        idx = self.cmb_model.findText(DEFAULT_MODEL_NAME)
        if idx >= 0:
            self.cmb_model.setCurrentIndex(idx)

    # ---------- public API ----------
    def current_model_path(self) -> str:
        return self.cmb_model.currentData() or ""

    def is_enabled(self) -> bool:
        return self.btn_enable.isChecked()

    def set_status(self, msg: str):
        self.lbl_status.setText(msg)

    def set_fps(self, fps: float):
        self.lbl_fps.setText("%.1f" % fps if fps > 0 else "—")

    def set_detection_count(self, n: int):
        self.lbl_count.setText(str(n))

    def reset_runtime(self):
        self.lbl_fps.setText("—")
        self.lbl_count.setText("0")

    # ---------- handlers ----------
    def _on_toggle(self, on):
        self.btn_enable.setText("AI 추론 활성  (클릭하여 정지)" if on
                                else "AI 추론 활성화")
        if not on:
            self.reset_runtime()
        self.enable_changed.emit(on)

    def _on_model_change(self):
        self.model_changed.emit(self.current_model_path())

    def _on_conf_value_changed(self, v):
        c = v / 100.0
        self.lbl_conf.setText("%.2f" % c)
        # live-emit only when not actively dragging (keyboard arrow / step click)
        if not self.sld_conf.isSliderDown():
            self.conf_changed.emit(c)

    def _on_conf_released(self):
        self.conf_changed.emit(self.sld_conf.value() / 100.0)
