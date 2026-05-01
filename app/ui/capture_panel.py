# app/ui/capture_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from PyQt5 import QtCore, QtWidgets

from .style import make_separator


class CapturePanel(QtWidgets.QGroupBox):
    new_seq = QtCore.pyqtSignal(str)
    output_dir_changed = QtCore.pyqtSignal(str)

    snap_bf = QtCore.pyqtSignal()
    snap_dpcx = QtCore.pyqtSignal()
    snap_dpcy = QtCore.pyqtSignal()
    snap_pseudo = QtCore.pyqtSignal()

    dpc_capture = QtCore.pyqtSignal()
    dpc_capture_and_save_all = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("촬영", parent)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        # ---- Output directory ----
        lbl_out = QtWidgets.QLabel("저장 폴더")
        lbl_out.setProperty("role", "caption")
        root.addWidget(lbl_out)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(6)
        self.ed_out = QtWidgets.QLineEdit(os.path.expanduser("~/RAIM_OUTPUT"))
        self.btn_out = QtWidgets.QPushButton("…")
        self.btn_out.setProperty("role", "ghost")
        self.btn_out.setFixedWidth(36)
        row1.addWidget(self.ed_out, 1)
        row1.addWidget(self.btn_out)
        root.addLayout(row1)

        # ---- Sequence name ----
        lbl_seq = QtWidgets.QLabel("시퀀스 이름")
        lbl_seq.setProperty("role", "caption")
        root.addWidget(lbl_seq)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(6)
        self.ed_seq = QtWidgets.QLineEdit("sample")
        self.btn_new = QtWidgets.QPushButton("새로 만들기")
        self.btn_new.setProperty("role", "ghost")
        self.btn_new.setFixedWidth(96)
        row2.addWidget(self.ed_seq, 1)
        row2.addWidget(self.btn_new)
        root.addLayout(row2)

        root.addSpacing(2)
        root.addWidget(make_separator("h"))
        root.addSpacing(2)

        # ---- Snapshot buttons ----
        lbl_snap = QtWidgets.QLabel("현재 채널 저장")
        lbl_snap.setProperty("role", "caption")
        root.addWidget(lbl_snap)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(6)
        self.btn_bf = QtWidgets.QPushButton("BF")
        self.btn_dx = QtWidgets.QPushButton("DPCx")
        self.btn_dy = QtWidgets.QPushButton("DPCy")
        self.btn_prgb = QtWidgets.QPushButton("합성 RGB")
        grid.addWidget(self.btn_bf,   0, 0)
        grid.addWidget(self.btn_dx,   0, 1)
        grid.addWidget(self.btn_dy,   1, 0)
        grid.addWidget(self.btn_prgb, 1, 1)
        root.addLayout(grid)

        root.addSpacing(2)
        root.addWidget(make_separator("h"))
        root.addSpacing(2)

        # ---- DPC capture row (primary actions) ----
        lbl_dpc = QtWidgets.QLabel("DPC 촬영")
        lbl_dpc.setProperty("role", "caption")
        root.addWidget(lbl_dpc)

        self.btn_dpc = QtWidgets.QPushButton("DPC 촬영")
        self.btn_dpc.setProperty("role", "primary")
        self.btn_dpc.setMinimumHeight(34)
        self.btn_dpc.setToolTip(
            "BF + DPCx + DPCy + 합성RGB 단계별 촬영"
        )
        root.addWidget(self.btn_dpc)

        self.btn_dpc_all = QtWidgets.QPushButton("촬영 + 전체 저장")
        self.btn_dpc_all.setProperty("role", "success")
        self.btn_dpc_all.setMinimumHeight(34)
        self.btn_dpc_all.setToolTip(
            "DPC 시퀀스 촬영 후 모든 채널을 디스크에 저장"
        )
        root.addWidget(self.btn_dpc_all)

        root.addStretch(1)

        # ---- signals ----
        self.btn_out.clicked.connect(self._pick_out)
        self.ed_out.editingFinished.connect(
            lambda: self.output_dir_changed.emit(self.ed_out.text().strip())
        )
        self.btn_new.clicked.connect(
            lambda: self.new_seq.emit(self.ed_seq.text().strip())
        )

        self.btn_bf.clicked.connect(self.snap_bf.emit)
        self.btn_dx.clicked.connect(self.snap_dpcx.emit)
        self.btn_dy.clicked.connect(self.snap_dpcy.emit)
        self.btn_prgb.clicked.connect(self.snap_pseudo.emit)

        self.btn_dpc.clicked.connect(self.dpc_capture.emit)
        self.btn_dpc_all.clicked.connect(self.dpc_capture_and_save_all.emit)

    def _pick_out(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "저장 폴더 선택", self.ed_out.text().strip()
        )
        if d:
            self.ed_out.setText(d)
            self.output_dir_changed.emit(d)
