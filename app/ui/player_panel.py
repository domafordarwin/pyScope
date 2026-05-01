# app/ui/player_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from PyQt5 import QtCore, QtGui, QtWidgets
from ..capture.sequence_repo import list_sequence_images


class PlayerPanel(QtWidgets.QWidget):
    frame_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._seq_dir = ""
        self._frames = []
        self._idx = 0
        self._playing = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        top = QtWidgets.QHBoxLayout()
        self.lbl = QtWidgets.QLabel("시퀀스 플레이어")
        self.lbl.setProperty("role", "title")
        self.btn_load = QtWidgets.QPushButton("시퀀스 폴더 열기…")
        self.btn_load.setProperty("role", "ghost")
        self.btn_load.setFixedWidth(160)
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_load)
        root.addLayout(top)

        ctrl = QtWidgets.QHBoxLayout()
        self.btn_play = QtWidgets.QPushButton("재생")
        self.btn_play.setProperty("role", "primary")
        self.btn_prev = QtWidgets.QPushButton("◀")
        self.btn_next = QtWidgets.QPushButton("▶")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.pos = QtWidgets.QLabel("0/0")
        self.pos.setProperty("role", "value")
        for b in (self.btn_play, self.btn_prev, self.btn_next):
            b.setFixedWidth(70 if b is self.btn_play else 45)

        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.btn_prev)
        ctrl.addWidget(self.btn_next)
        ctrl.addWidget(self.slider, 1)
        ctrl.addWidget(self.pos)
        root.addLayout(ctrl)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._step)

        self.btn_load.clicked.connect(self._pick_dir)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_prev.clicked.connect(lambda: self.set_index(self._idx - 1))
        self.btn_next.clicked.connect(lambda: self.set_index(self._idx + 1))
        self.slider.valueChanged.connect(self.set_index)

    def _pick_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "시퀀스 폴더 선택", os.path.expanduser("~/RAIM_OUTPUT"))
        if d:
            self.load_sequence(d)

    def load_sequence(self, seq_dir: str):
        self._seq_dir = seq_dir
        self._frames = list_sequence_images(seq_dir)
        self._idx = 0
        self.slider.setRange(0, max(0, len(self._frames) - 1))
        self._update_label()
        if self._frames:
            self.frame_selected.emit(self._frames[self._idx])

    def set_index(self, i: int):
        if not self._frames:
            return
        i = max(0, min(len(self._frames) - 1, int(i)))
        self._idx = i
        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self._update_label()
        self.frame_selected.emit(self._frames[self._idx])

    def _update_label(self):
        self.pos.setText(f"{(self._idx+1) if self._frames else 0}/{len(self._frames)}")

    def _toggle_play(self):
        if not self._frames:
            return
        self._playing = not self._playing
        self.btn_play.setText("정지" if self._playing else "재생")
        # Re-apply role so primary/danger styling toggles when text changes
        self.btn_play.setProperty("role", "danger" if self._playing else "primary")
        self.btn_play.style().unpolish(self.btn_play)
        self.btn_play.style().polish(self.btn_play)
        if self._playing:
            self._timer.start()
        else:
            self._timer.stop()

    def _step(self):
        if not self._frames:
            return
        nxt = self._idx + 1
        if nxt >= len(self._frames):
            nxt = 0
        self.set_index(nxt)
