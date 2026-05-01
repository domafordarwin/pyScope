# app/ui/live_view.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cv2
from PyQt5 import QtCore, QtGui, QtWidgets
from ..util.image_convert import bgr_to_qimage


class LiveView(QtWidgets.QLabel):
    roi_changed = QtCore.pyqtSignal(object)  # (x,y,w,h) in image coords or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(720, 420)
        self.setProperty("role", "canvas")
        self.setText("신호 없음")

        self._frame_bgr = None
        self._pix = None

        self._dragging = False
        self._p0 = None  # in widget coords
        self._p1 = None

        self._roi_xywh = None  # in image coords
        self._detections = []  # List[Detection] from AI worker
        self._pending_labels = []  # [(class_id, class_name, x, y, w, h)]
        self._roi_locked = False

        self.setMouseTracking(True)

    def set_roi_locked(self, locked: bool):
        """잠금 시 마우스 드래그/우클릭이 ROI를 변경하지 못함."""
        self._roi_locked = bool(locked)
        self.setCursor(QtCore.Qt.ForbiddenCursor if self._roi_locked
                       else QtCore.Qt.ArrowCursor)

    def current_roi(self):
        return self._roi_xywh

    def clear_roi(self):
        self._roi_xywh = None
        self._p0 = None
        self._p1 = None
        self._dragging = False
        self.roi_changed.emit(None)
        self.update()

    # Display-only downsample target. The full-resolution frame is preserved
    # in self._frame_bgr (used for ROI coordinate calculation) — this only
    # shrinks the QPixmap that gets blitted to screen, eliminating the
    # 5MP × bgr_to_qimage hot loop that freezes the GUI thread.
    DISPLAY_MAX_WIDTH = 1280

    def set_detections(self, dets):
        """AI 추론 결과 (Detection 리스트) 를 받아 paintEvent로 표시."""
        self._detections = dets if dets else []
        self.update()

    def clear_detections(self):
        if self._detections:
            self._detections = []
            self.update()

    def set_pending_labels(self, labels):
        """라벨링 중인 박스 리스트 — DatasetPanel 에서 호출."""
        self._pending_labels = list(labels) if labels else []
        self.update()

    def clear_pending_labels(self):
        if self._pending_labels:
            self._pending_labels = []
            self.update()

    @staticmethod
    def _class_color(class_id):
        """Stable HSV-derived color per class."""
        h = (class_id * 37 + 11) % 360
        return QtGui.QColor.fromHsv(h, 200, 235)

    def set_frame(self, frame_bgr):
        self._frame_bgr = frame_bgr  # full res — used by _widget_to_image / ROI

        h, w = frame_bgr.shape[:2]
        if w > self.DISPLAY_MAX_WIDTH:
            scale = self.DISPLAY_MAX_WIDTH / float(w)
            disp = cv2.resize(
                frame_bgr,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        else:
            disp = frame_bgr

        qimg = bgr_to_qimage(disp)
        self._pix = QtGui.QPixmap.fromImage(qimg)
        self.update()

    def _pix_rect(self):
        if self._pix is None:
            return None
        # scaled pix rect in label coords
        pix = self._pix.scaled(self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        x = (self.width() - pix.width()) // 2
        y = (self.height() - pix.height()) // 2
        return QtCore.QRect(x, y, pix.width(), pix.height()), pix

    def _widget_to_image(self, p: QtCore.QPoint):
        if self._frame_bgr is None or self._pix is None:
            return None
        pr, pix = self._pix_rect()
        if pr is None or not pr.contains(p):
            return None
        fx = (p.x() - pr.x()) / max(1, pr.width())
        fy = (p.y() - pr.y()) / max(1, pr.height())
        H, W = self._frame_bgr.shape[:2]
        ix = int(fx * W)
        iy = int(fy * H)
        ix = max(0, min(W - 1, ix))
        iy = max(0, min(H - 1, iy))
        return ix, iy

    def mousePressEvent(self, ev):
        if self._roi_locked:
            return
        if ev.button() == QtCore.Qt.RightButton:
            self.clear_roi()
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        if self._frame_bgr is None:
            return
        self._dragging = True
        self._p0 = ev.pos()
        self._p1 = ev.pos()
        self.update()

    def mouseMoveEvent(self, ev):
        if self._roi_locked or not self._dragging:
            return
        self._p1 = ev.pos()
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._roi_locked:
            return
        if ev.button() != QtCore.Qt.LeftButton:
            return
        if not self._dragging:
            return
        self._dragging = False

        p0 = self._p0
        p1 = self._p1
        self._p0 = None
        self._p1 = None

        if p0 is None or p1 is None:
            return

        a = self._widget_to_image(p0)
        b = self._widget_to_image(p1)
        if a is None or b is None:
            self._roi_xywh = None
            self.roi_changed.emit(None)
            self.update()
            return

        x0, y0 = a
        x1, y1 = b
        x = min(x0, x1)
        y = min(y0, y1)
        w = abs(x1 - x0)
        h = abs(y1 - y0)

        if w < 10 or h < 10:
            self._roi_xywh = None
            self.roi_changed.emit(None)
        else:
            self._roi_xywh = (x, y, w, h)
            self.roi_changed.emit(self._roi_xywh)

        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._pix is None:
            return

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        pr, pix = self._pix_rect()
        p.drawPixmap(pr, pix)

        # ROI overlay in widget coords (draw from drag points if dragging)
        if self._dragging and self._p0 and self._p1:
            r = QtCore.QRect(self._p0, self._p1).normalized()
            p.setPen(QtGui.QPen(QtGui.QColor(118, 177, 222, 220), 2))
            p.setBrush(QtGui.QColor(118, 177, 222, 50))
            p.drawRoundedRect(QtCore.QRectF(r), 8, 8)

        # show current ROI also
        if (not self._dragging) and self._roi_xywh and self._frame_bgr is not None:
            x, y, w, h = self._roi_xywh
            H, W = self._frame_bgr.shape[:2]

            pr, _ = self._pix_rect()
            # map image roi to widget rect
            rx = pr.x() + int((x / W) * pr.width())
            ry = pr.y() + int((y / H) * pr.height())
            rw = int((w / W) * pr.width())
            rh = int((h / H) * pr.height())
            r = QtCore.QRect(rx, ry, rw, rh)
            p.setPen(QtGui.QPen(QtGui.QColor(118, 177, 222, 230), 2))
            p.setBrush(QtGui.QColor(118, 177, 222, 40))
            p.drawRoundedRect(QtCore.QRectF(r), 8, 8)

        # AI 검출 박스 overlay (이미지 좌표 → 위젯 좌표 매핑)
        if self._detections and self._frame_bgr is not None:
            H, W = self._frame_bgr.shape[:2]
            pr, _ = self._pix_rect()
            sx = pr.width() / float(W)
            sy = pr.height() / float(H)
            font = p.font()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            fm = QtGui.QFontMetrics(font)
            for det in self._detections:
                color = self._class_color(det.class_id)
                rx = pr.x() + int(det.x1 * sx)
                ry = pr.y() + int(det.y1 * sy)
                rw = max(2, int((det.x2 - det.x1) * sx))
                rh = max(2, int((det.y2 - det.y1) * sy))
                # bbox stroke
                p.setBrush(QtCore.Qt.NoBrush)
                p.setPen(QtGui.QPen(color, 2))
                p.drawRect(rx, ry, rw, rh)
                # label pill above the box (or below if too close to top)
                label = "%s  %.0f%%" % (det.class_name, det.confidence * 100)
                tw = fm.horizontalAdvance(label) + 10
                th = fm.height() + 4
                ly = ry - th if ry - th > pr.y() else ry + rh
                p.setBrush(color)
                p.setPen(QtCore.Qt.NoPen)
                p.drawRect(rx, ly, tw, th)
                p.setPen(QtGui.QPen(QtCore.Qt.white))
                p.drawText(rx + 5, ly + fm.ascent() + 2, label)

        # Pending labels overlay — 데이터셋 탭에서 라벨링 중인 박스
        # (점선 + 📌 마커 — AI 박스(실선)와 시각 구분)
        if self._pending_labels and self._frame_bgr is not None:
            try:
                from ..dataset import ONION_MITOSIS_KOREAN
            except Exception:
                ONION_MITOSIS_KOREAN = {}
            H, W = self._frame_bgr.shape[:2]
            pr, _ = self._pix_rect()
            sx = pr.width() / float(W)
            sy = pr.height() / float(H)
            font = p.font()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            fm = QtGui.QFontMetrics(font)
            for entry in self._pending_labels:
                cls_id = int(entry[0])
                cls_name = str(entry[1])
                x = float(entry[2]); y = float(entry[3])
                w = float(entry[4]); h = float(entry[5])
                color = self._class_color(cls_id)
                rx = pr.x() + int(x * sx)
                ry = pr.y() + int(y * sy)
                rw = max(2, int(w * sx))
                rh = max(2, int(h * sy))
                # 점선 박스 (라벨링 박스 = AI 박스와 시각 구분)
                pen = QtGui.QPen(color, 3, QtCore.Qt.DashLine)
                p.setPen(pen)
                fill = QtGui.QColor(color.red(), color.green(), color.blue(), 45)
                p.setBrush(fill)
                p.drawRect(rx, ry, rw, rh)
                # 한국어 라벨 (📌 마커)
                kr = ONION_MITOSIS_KOREAN.get(cls_name, cls_name)
                label = "📌  %s" % kr
                tw = fm.horizontalAdvance(label) + 12
                th = fm.height() + 4
                ly = ry - th if ry - th > pr.y() else ry + rh
                p.setBrush(color)
                p.setPen(QtCore.Qt.NoPen)
                p.drawRect(rx, ly, tw, th)
                p.setPen(QtGui.QPen(QtCore.Qt.white))
                p.drawText(rx + 6, ly + fm.ascent() + 2, label)
