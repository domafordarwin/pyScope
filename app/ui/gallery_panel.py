# app/ui/gallery_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GalleryPanel — thumbnail strip of saved PNGs.

Two performance escape hatches keep this responsive even with 5 MP captures:
  1. refresh() is debounced (200 ms) — `Capture + Save ALL` triggers four
     `saved` signals back-to-back; without debounce the GUI freezes while
     the same gallery rebuild runs four times in a row.
  2. Thumbnails are decoded and downscaled in a worker thread via cv2,
     and the resulting QPixmap is sent back via a Qt signal. The GUI
     thread only ever does the cheap list-item insertion / icon assignment.
"""

import os

import cv2
from PyQt5 import QtCore, QtGui, QtWidgets

from ..capture.sequence_repo import list_all_images, make_thumb_label


THUMB_W, THUMB_H = 160, 110
GALLERY_LIMIT = 200         # show the last N PNGs (newest first)
REFRESH_DEBOUNCE_MS = 200


# =====================================================================
# Background thumbnail loader (lives on a worker QThread)
# =====================================================================
class _ThumbnailLoader(QtCore.QObject):
    thumb_ready = QtCore.pyqtSignal(str, QtGui.QImage)
    failed = QtCore.pyqtSignal(str)

    @QtCore.pyqtSlot(str)
    def load(self, path):
        try:
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                self.failed.emit(path)
                return
            if img.ndim == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            h, w = img.shape[:2]
            scale = min(THUMB_W / float(w), THUMB_H / float(h), 1.0)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            thumb = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
            qimg = QtGui.QImage(
                rgb.data, nw, nh, nw * 3, QtGui.QImage.Format_RGB888
            ).copy()  # copy() — buffer outlives the numpy array
            self.thumb_ready.emit(path, qimg)
        except Exception:
            self.failed.emit(path)


# =====================================================================
# GalleryPanel
# =====================================================================
class GalleryPanel(QtWidgets.QWidget):
    image_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        top = QtWidgets.QHBoxLayout()
        self.lbl = QtWidgets.QLabel("갤러리")
        self.lbl.setProperty("role", "title")
        self.btn_delete = QtWidgets.QPushButton("🗑  선택 삭제")
        self.btn_delete.setProperty("role", "danger")
        self.btn_delete.setFixedWidth(120)
        self.btn_delete.setEnabled(False)
        self.btn_refresh = QtWidgets.QPushButton("새로고침")
        self.btn_refresh.setProperty("role", "ghost")
        self.btn_refresh.setFixedWidth(100)
        top.addWidget(self.lbl)
        top.addStretch(1)
        top.addWidget(self.btn_delete)
        top.addWidget(self.btn_refresh)
        root.addLayout(top)

        self.listw = QtWidgets.QListWidget()
        self.listw.setViewMode(QtWidgets.QListView.IconMode)
        self.listw.setResizeMode(QtWidgets.QListView.Adjust)
        self.listw.setMovement(QtWidgets.QListView.Static)
        # 그리드 모드: 가로/세로 모두 영역 채워 wrap
        self.listw.setFlow(QtWidgets.QListView.LeftToRight)
        self.listw.setWrapping(True)
        self.listw.setUniformItemSizes(True)
        self.listw.setIconSize(QtCore.QSize(THUMB_W, THUMB_H))
        self.listw.setGridSize(QtCore.QSize(THUMB_W + 24, THUMB_H + 40))
        self.listw.setSpacing(8)
        # 다중 선택 + 삭제
        self.listw.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.listw.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        # 영역 채우기 (FixedHeight 제거 — 부모 레이아웃에 맞춰 확장)
        self.listw.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        root.addWidget(self.listw, 1)

        self._output_dir = os.path.expanduser("~/RAIM_OUTPUT")
        self._items_by_path = {}  # path -> QListWidgetItem (for async thumb update)

        # ---- debounce timer ----
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(REFRESH_DEBOUNCE_MS)
        self._refresh_timer.timeout.connect(self._do_refresh)

        # ---- thumbnail worker thread ----
        self._thumb_thread = QtCore.QThread(self)
        self._thumb_loader = _ThumbnailLoader()
        self._thumb_loader.moveToThread(self._thumb_thread)
        self._thumb_loader.thumb_ready.connect(self._on_thumb_ready)
        self._thumb_thread.start()

        # ---- signals ----
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.listw.itemClicked.connect(self._on_item_clicked)
        self.listw.itemSelectionChanged.connect(self._update_delete_btn)
        self.listw.customContextMenuRequested.connect(self._show_context_menu)
        # Delete 키로도 삭제
        QtWidgets.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key_Delete), self.listw,
            activated=self._delete_selected,
        )

    # ---------- public API ----------
    def set_output_dir(self, outdir: str):
        self._output_dir = outdir
        self.refresh()

    def refresh(self):
        """Schedule a refresh — debounced so multiple back-to-back calls
        (e.g. four save_snapshot in quick succession) coalesce into one."""
        self._refresh_timer.start()

    # ---------- internals ----------
    def _do_refresh(self):
        self.listw.clear()
        self._items_by_path.clear()

        try:
            paths = list_all_images(self._output_dir)
        except Exception:
            paths = []
        # newest last by default; show newest first, capped at GALLERY_LIMIT
        paths = paths[-GALLERY_LIMIT:]

        for p in reversed(paths):
            item = QtWidgets.QListWidgetItem(make_thumb_label(p))
            item.setData(QtCore.Qt.UserRole, p)
            # placeholder icon prevents layout jump when real thumb arrives
            item.setSizeHint(QtCore.QSize(THUMB_W + 16, THUMB_H + 28))
            self.listw.addItem(item)
            self._items_by_path[p] = item
            # request thumbnail asynchronously
            QtCore.QMetaObject.invokeMethod(
                self._thumb_loader,
                "load",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, p),
            )

    @QtCore.pyqtSlot(str, QtGui.QImage)
    def _on_thumb_ready(self, path, qimg):
        item = self._items_by_path.get(path)
        if item is None:
            return
        pix = QtGui.QPixmap.fromImage(qimg)
        item.setIcon(QtGui.QIcon(pix))

    def _on_item_clicked(self, item):
        p = item.data(QtCore.Qt.UserRole)
        if p:
            self.image_selected.emit(p)

    # ---------- selection / delete ----------
    def _update_delete_btn(self):
        self.btn_delete.setEnabled(bool(self.listw.selectedItems()))

    def _show_context_menu(self, pos: QtCore.QPoint):
        item = self.listw.itemAt(pos)
        if item is None:
            return
        # 클릭한 항목이 선택에 없으면 단독 선택으로 전환
        if not item.isSelected():
            self.listw.clearSelection()
            item.setSelected(True)
        menu = QtWidgets.QMenu(self)
        act_open = menu.addAction("🔍  열기")
        act_show = menu.addAction("📂  탐색기에서 보기")
        menu.addSeparator()
        act_del = menu.addAction("🗑  삭제")
        act = menu.exec_(self.listw.mapToGlobal(pos))
        if act is act_open:
            self._on_item_clicked(item)
        elif act is act_show:
            self._reveal_in_explorer(item.data(QtCore.Qt.UserRole))
        elif act is act_del:
            self._delete_selected()

    def _reveal_in_explorer(self, path: str):
        if not path or not os.path.exists(path):
            return
        url = QtCore.QUrl.fromLocalFile(os.path.dirname(path))
        QtGui.QDesktopServices.openUrl(url)

    def _delete_selected(self):
        items = self.listw.selectedItems()
        if not items:
            return
        paths = [it.data(QtCore.Qt.UserRole) for it in items]
        paths = [p for p in paths if p]
        if not paths:
            return
        n = len(paths)
        first = os.path.basename(paths[0])
        msg = (
            "이미지 1장을 삭제할까요?\n\n%s" % first if n == 1
            else "선택한 %d장을 모두 삭제할까요?\n첫 번째: %s\n\n"
                 "이 작업은 되돌릴 수 없습니다." % (n, first)
        )
        reply = QtWidgets.QMessageBox.question(
            self, "갤러리 — 이미지 삭제", msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        deleted = 0
        for p in paths:
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    deleted += 1
                self._items_by_path.pop(p, None)
            except OSError:
                pass
        self.refresh()
        if deleted:
            QtWidgets.QToolTip.showText(
                self.btn_delete.mapToGlobal(QtCore.QPoint(0, -28)),
                "%d장 삭제됨" % deleted, self.btn_delete,
            )

    def closeEvent(self, ev):
        # Tear down worker thread cleanly
        self._thumb_thread.quit()
        self._thumb_thread.wait(1000)
        super().closeEvent(ev)
