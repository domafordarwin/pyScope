# app/ui/detect_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DetectPanel — AI 추론 컨트롤 + 검출 통계 시각화.

내부에 AIPanel을 호스트 + 검출 결과 누적 통계 (분열 단계별 카운트).
"""

from collections import Counter
from PyQt5 import QtCore, QtWidgets

from .style import Color, make_separator
from .ai_panel import AIPanel
from ..dataset import ONION_MITOSIS_KOREAN


class DetectPanel(QtWidgets.QWidget):
    """AI 추론 컨트롤 + 실시간 통계."""

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        head = QtWidgets.QLabel("AI 검출  ·  Hailo-10H NPU")
        head.setProperty("role", "title")
        root.addWidget(head)

        # AIPanel을 그대로 호스트 (모델/신뢰도/FPS 컨트롤)
        self.ai_panel = AIPanel()
        root.addWidget(self.ai_panel)

        root.addWidget(make_separator("h"))

        # 통계 영역
        cap_stats = QtWidgets.QLabel("실시간 검출 통계")
        cap_stats.setProperty("role", "caption")
        root.addWidget(cap_stats)

        self.lbl_total = QtWidgets.QLabel("총 검출: 0")
        self.lbl_total.setProperty("role", "value")
        root.addWidget(self.lbl_total)

        # 클래스별 카운트 표시 영역 (실시간 갱신)
        self.lbl_per_class = QtWidgets.QLabel("(아직 검출 없음)")
        self.lbl_per_class.setProperty("role", "muted")
        self.lbl_per_class.setWordWrap(True)
        root.addWidget(self.lbl_per_class)

        # 누적 통계 (세션 시작 후 합계)
        cap_cum = QtWidgets.QLabel("세션 누적")
        cap_cum.setProperty("role", "caption")
        root.addWidget(cap_cum)

        self.lbl_cumulative = QtWidgets.QLabel("0 검출 / 0 프레임")
        self.lbl_cumulative.setProperty("role", "value")
        root.addWidget(self.lbl_cumulative)

        # Reset 버튼
        self.btn_reset = QtWidgets.QPushButton("누적 통계 초기화")
        self.btn_reset.setProperty("role", "ghost")
        self.btn_reset.clicked.connect(self._reset_cumulative)
        root.addWidget(self.btn_reset)

        root.addStretch(1)

        # state
        self._session_total_dets = 0
        self._session_total_frames = 0
        self._session_per_class = Counter()

    # --------------------------------------------------------------
    @QtCore.pyqtSlot(list)
    def update_detections(self, detections):
        """main_window가 ai_worker.detections_ready를 여기로 라우팅."""
        n = len(detections)
        self._session_total_dets += n
        self._session_total_frames += 1

        # 현재 프레임 클래스별
        cur = Counter(d.class_name for d in detections)
        for cls, c in cur.items():
            self._session_per_class[cls] += c

        # 현재 프레임 표시
        self.lbl_total.setText("현재 프레임: %d 검출" % n)
        if cur:
            lines = []
            for cls_name, c in cur.most_common():
                kr = ONION_MITOSIS_KOREAN.get(cls_name, cls_name)
                lines.append("  • %s (%s) : %d" % (kr, cls_name, c))
            self.lbl_per_class.setText("\n".join(lines))
        else:
            self.lbl_per_class.setText("(현재 프레임에 검출 없음)")

        # 누적
        avg = (self._session_total_dets / self._session_total_frames
               if self._session_total_frames > 0 else 0)
        self.lbl_cumulative.setText(
            "%d 검출 / %d 프레임 (평균 %.1f/프레임)" %
            (self._session_total_dets, self._session_total_frames, avg)
        )

    def _reset_cumulative(self):
        self._session_total_dets = 0
        self._session_total_frames = 0
        self._session_per_class.clear()
        self.lbl_cumulative.setText("0 검출 / 0 프레임")
