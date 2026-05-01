# app/ui/image_viewer.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ImageViewerDialog — modal popup for inspecting captured images.

Opens at 80% of the available screen, fits the image to the viewport by
default, and supports zoom/pan via toolbar buttons or Ctrl+wheel.
Designed for the multi-megapixel frames produced by the OS-CM50 camera.
"""

import os

import cv2
from PyQt5 import QtCore, QtGui, QtWidgets

from ..util.image_convert import bgr_to_qimage
from .style import Color


class ImageViewerDialog(QtWidgets.QDialog):
    MIN_ZOOM = 0.05
    MAX_ZOOM = 12.0

    def __init__(self, image_path, parent=None, prefetched_bgr=None,
                 image_list=None):
        """
        prefetched_bgr: if the caller already loaded the image (e.g. from
        the gallery click handler), pass it to skip a redundant cv2.imread
        on the GUI thread — eliminates the perceived "freeze" when opening
        a 5MP capture.

        image_list: optional list of absolute image paths to enable
        prev/next navigation. The current image_path must be present in
        the list. When omitted, navigation buttons are hidden.
        """
        super().__init__(parent)
        self.image_path = image_path
        self.setWindowTitle("이미지 뷰어 — " + os.path.basename(image_path))
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMaximizeButtonHint)

        # Open at 80% of available screen
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * 0.8), int(screen.height() * 0.85))

        # Navigation state
        self._image_list = list(image_list) if image_list else [image_path]
        try:
            self._index = self._image_list.index(image_path)
        except ValueError:
            self._image_list = [image_path]
            self._index = 0

        if prefetched_bgr is not None:
            self._orig_pix = self._pixmap_from_bgr(prefetched_bgr)
        else:
            self._orig_pix = self._load_pixmap(image_path)

        self._zoom = 1.0
        self._fit_mode = True

        # Pan (drag-to-scroll) state
        self._panning = False
        self._pan_anchor = QtCore.QPoint()
        self._scroll_anchor = (0, 0)

        self._build_ui()

        # Install pan event filter on the scroll viewport
        self.scroll.viewport().installEventFilter(self)
        self._update_pan_cursor()
        self._update_nav_state()

        # Defer initial fit until widget is laid out
        QtCore.QTimer.singleShot(0, self._fit_to_window)

        # ESC to close
        QtWidgets.QShortcut(QtGui.QKeySequence("Esc"), self, activated=self.accept)
        # Ctrl+0 = fit, Ctrl+1 = 100%
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+0"), self,
                            activated=self._fit_to_window)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+1"), self,
                            activated=lambda: self._set_zoom(1.0))
        # 네비게이션 단축키: ←/→ , Home/End, PgUp/PgDn
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Left),  self,
                            activated=self._show_prev)
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Right), self,
                            activated=self._show_next)
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_PageUp), self,
                            activated=self._show_prev)
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_PageDown), self,
                            activated=self._show_next)
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Home), self,
                            activated=lambda: self._goto(0))
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_End), self,
                            activated=lambda: self._goto(len(self._image_list) - 1))

    # ---------- image loading ----------
    @staticmethod
    def _pixmap_from_bgr(img_bgr):
        if img_bgr is None:
            return None
        if img_bgr.ndim == 2:
            img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
        qimg = bgr_to_qimage(img_bgr)
        return QtGui.QPixmap.fromImage(qimg)

    @classmethod
    def _load_pixmap(cls, path):
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        return cls._pixmap_from_bgr(img)

    @staticmethod
    def _format_bytes(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return "%.1f %s" % (n, unit)
            n /= 1024.0
        return "%.1f TB" % n

    # ---------- UI ----------
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ---- Header (filename + dimensions + filesize) ----
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)

        self.lbl_title = QtWidgets.QLabel(os.path.basename(self.image_path))
        self.lbl_title.setProperty("role", "title")
        header.addWidget(self.lbl_title)

        header.addStretch(1)

        if self._orig_pix is not None:
            try:
                size_bytes = os.path.getsize(self.image_path)
            except OSError:
                size_bytes = 0
            info_text = "%d × %d  ·  %s" % (
                self._orig_pix.width(),
                self._orig_pix.height(),
                self._format_bytes(size_bytes),
            )
        else:
            info_text = "이미지를 불러올 수 없습니다"
        self.lbl_info = QtWidgets.QLabel(info_text)
        self.lbl_info.setProperty("role", "muted")
        header.addWidget(self.lbl_info)

        layout.addLayout(header)

        # ---- Image canvas (dark, scrollable) ----
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(QtCore.Qt.AlignCenter)
        self.scroll.setStyleSheet(
            "QScrollArea { background: %s; border: 1px solid %s;"
            " border-radius: 8px; }" % (Color.CANVAS_DARK, Color.BORDER_DEFAULT)
        )

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet(
            "background: %s; color: %s;" % (Color.CANVAS_DARK, Color.TEXT_MUTED)
        )
        if self._orig_pix is None:
            self.image_label.setText("이미지를 불러올 수 없습니다")
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll, 1)

        # ---- Toolbar ----
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(6)

        self.btn_fit = QtWidgets.QPushButton("화면 맞춤")
        self.btn_fit.setProperty("role", "ghost")
        self.btn_fit.setToolTip("창 크기에 맞춤 (Ctrl+0)")

        self.btn_100 = QtWidgets.QPushButton("원본 100%")
        self.btn_100.setProperty("role", "ghost")
        self.btn_100.setToolTip("원본 픽셀 1:1 (Ctrl+1)")

        self.btn_zoom_out = QtWidgets.QPushButton("－")
        self.btn_zoom_out.setProperty("role", "ghost")
        self.btn_zoom_out.setFixedWidth(40)
        self.btn_zoom_out.setToolTip("축소")

        self.btn_zoom_in = QtWidgets.QPushButton("＋")
        self.btn_zoom_in.setProperty("role", "ghost")
        self.btn_zoom_in.setFixedWidth(40)
        self.btn_zoom_in.setToolTip("확대 (Ctrl+휠 가능)")

        self.lbl_zoom = QtWidgets.QLabel("Fit")
        self.lbl_zoom.setProperty("role", "value")
        self.lbl_zoom.setMinimumWidth(64)
        self.lbl_zoom.setAlignment(QtCore.Qt.AlignCenter)

        self.btn_prev = QtWidgets.QPushButton("◀  이전")
        self.btn_prev.setProperty("role", "ghost")
        self.btn_prev.setToolTip("이전 이미지 (← / PgUp)")
        self.btn_next = QtWidgets.QPushButton("다음  ▶")
        self.btn_next.setProperty("role", "ghost")
        self.btn_next.setToolTip("다음 이미지 (→ / PgDn)")
        self.lbl_nav = QtWidgets.QLabel("")
        self.lbl_nav.setProperty("role", "muted")
        self.lbl_nav.setMinimumWidth(72)
        self.lbl_nav.setAlignment(QtCore.Qt.AlignCenter)

        self.btn_close = QtWidgets.QPushButton("닫기 (Esc)")
        self.btn_close.setProperty("role", "primary")

        toolbar.addWidget(self.btn_fit)
        toolbar.addWidget(self.btn_100)
        toolbar.addSpacing(8)
        toolbar.addWidget(self.btn_zoom_out)
        toolbar.addWidget(self.lbl_zoom)
        toolbar.addWidget(self.btn_zoom_in)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_prev)
        toolbar.addWidget(self.lbl_nav)
        toolbar.addWidget(self.btn_next)
        toolbar.addSpacing(8)
        toolbar.addWidget(self.btn_close)
        layout.addLayout(toolbar)

        # signals
        self.btn_fit.clicked.connect(self._fit_to_window)
        self.btn_100.clicked.connect(lambda: self._set_zoom(1.0))
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_by(1.25))
        self.btn_zoom_out.clicked.connect(lambda: self._zoom_by(0.8))
        self.btn_prev.clicked.connect(self._show_prev)
        self.btn_next.clicked.connect(self._show_next)
        self.btn_close.clicked.connect(self.accept)

    # ---------- navigation ----------
    def _update_nav_state(self):
        n = len(self._image_list)
        self.lbl_nav.setText("%d / %d" % (self._index + 1, n))
        self.btn_prev.setEnabled(self._index > 0)
        self.btn_next.setEnabled(self._index < n - 1)

    def _show_prev(self):
        if self._index > 0:
            self._goto(self._index - 1)

    def _show_next(self):
        if self._index < len(self._image_list) - 1:
            self._goto(self._index + 1)

    def _goto(self, idx: int):
        if idx < 0 or idx >= len(self._image_list):
            return
        path = self._image_list[idx]
        if not os.path.isfile(path):
            # 파일 사라짐 → 리스트에서 빼고 같은 인덱스 재시도
            self._image_list.pop(idx)
            if not self._image_list:
                self.accept()
                return
            self._goto(min(idx, len(self._image_list) - 1))
            return
        self._index = idx
        self.image_path = path
        new_pix = self._load_pixmap(path)
        if new_pix is None:
            return
        self._orig_pix = new_pix
        # 헤더/타이틀 갱신
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            size_bytes = 0
        self.lbl_title.setText(os.path.basename(path))
        self.lbl_info.setText("%d × %d  ·  %s" % (
            new_pix.width(), new_pix.height(), self._format_bytes(size_bytes)
        ))
        self.setWindowTitle("이미지 뷰어 — " + os.path.basename(path))
        # Fit 모드 유지 — 새 이미지 적용
        if self._fit_mode:
            self._fit_to_window()
        else:
            self._set_zoom(self._zoom)
        self._update_nav_state()

    # ---------- zoom / fit ----------
    def _fit_to_window(self):
        if self._orig_pix is None:
            return
        view_size = self.scroll.viewport().size()
        if view_size.width() < 10 or view_size.height() < 10:
            # Layout not ready yet; try again on next tick
            QtCore.QTimer.singleShot(50, self._fit_to_window)
            return
        self._fit_mode = True
        scaled = self._orig_pix.scaled(
            view_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())
        if self._orig_pix.width() > 0:
            self._zoom = scaled.width() / float(self._orig_pix.width())
        self.lbl_zoom.setText("Fit")
        self._update_pan_cursor()

    def _set_zoom(self, z):
        if self._orig_pix is None:
            return
        self._fit_mode = False
        z = max(self.MIN_ZOOM, min(self.MAX_ZOOM, z))
        self._zoom = z
        new_size = self._orig_pix.size() * z
        scaled = self._orig_pix.scaled(
            new_size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())
        self.lbl_zoom.setText("%d%%" % int(round(z * 100)))
        self._update_pan_cursor()

    def _zoom_by(self, factor):
        self._set_zoom(self._zoom * factor)

    # ---------- pan (drag-to-scroll) ----------
    def _can_pan(self):
        """Image is large enough for scrollbars to be meaningful."""
        if self._orig_pix is None:
            return False
        vp = self.scroll.viewport().size()
        img = self.image_label.size()
        return img.width() > vp.width() or img.height() > vp.height()

    def _update_pan_cursor(self):
        """OpenHand when pan is possible, default cursor when fit."""
        vp = self.scroll.viewport()
        if self._can_pan():
            vp.setCursor(QtCore.Qt.OpenHandCursor)
        else:
            vp.unsetCursor()

    def eventFilter(self, obj, ev):
        if obj is self.scroll.viewport():
            t = ev.type()
            # Drag-to-pan
            if t == QtCore.QEvent.MouseButtonPress \
                    and ev.button() == QtCore.Qt.LeftButton \
                    and self._can_pan():
                self._panning = True
                self._pan_anchor = ev.pos()
                self._scroll_anchor = (
                    self.scroll.horizontalScrollBar().value(),
                    self.scroll.verticalScrollBar().value(),
                )
                self.scroll.viewport().setCursor(QtCore.Qt.ClosedHandCursor)
                return True
            elif t == QtCore.QEvent.MouseMove and self._panning:
                delta = ev.pos() - self._pan_anchor
                self.scroll.horizontalScrollBar().setValue(
                    self._scroll_anchor[0] - delta.x()
                )
                self.scroll.verticalScrollBar().setValue(
                    self._scroll_anchor[1] - delta.y()
                )
                return True
            elif t == QtCore.QEvent.MouseButtonRelease \
                    and ev.button() == QtCore.Qt.LeftButton \
                    and self._panning:
                self._panning = False
                self._update_pan_cursor()
                return True
            # Double-click toggles Fit ↔ 100%
            elif t == QtCore.QEvent.MouseButtonDblClick \
                    and ev.button() == QtCore.Qt.LeftButton:
                if self._fit_mode:
                    self._set_zoom(1.0)
                else:
                    self._fit_to_window()
                return True
        return super().eventFilter(obj, ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._fit_mode:
            QtCore.QTimer.singleShot(0, self._fit_to_window)
        else:
            QtCore.QTimer.singleShot(0, self._update_pan_cursor)

    # ---------- events ----------
    def wheelEvent(self, ev):
        if ev.modifiers() & QtCore.Qt.ControlModifier:
            delta = ev.angleDelta().y()
            if delta > 0:
                self._zoom_by(1.15)
            elif delta < 0:
                self._zoom_by(1.0 / 1.15)
            ev.accept()
            return
        super().wheelEvent(ev)
