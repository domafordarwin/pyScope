# app/ui/preview.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cv2
from PyQt5 import QtCore, QtGui, QtWidgets
from ..util.image_convert import bgr_to_qimage, gray_to_qimage


class PreviewView(QtWidgets.QLabel):
    """
    Channel preview canvas. Pre-downsamples large frames before the
    QImage/QPixmap conversion so feeding a 5MP live frame here doesn't
    block the GUI thread.
    """

    # Cap pre-conversion size at ~1.5× widget width — anything larger is
    # invisible after the final scaled() call but extremely expensive to
    # convert via bgr_to_qimage / QPixmap.fromImage.
    DISPLAY_OVERSAMPLE = 1.5

    def __init__(self, title="미리보기", parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(380, 200)
        self.setText(title)
        self.setProperty("role", "canvas")

    def _prescale_bgr(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        target_w = max(self.width(), 380) * self.DISPLAY_OVERSAMPLE
        if w > target_w:
            scale = target_w / float(w)
            return cv2.resize(
                frame_bgr,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        return frame_bgr

    def _prescale_gray(self, gray_u8):
        h, w = gray_u8.shape[:2]
        target_w = max(self.width(), 380) * self.DISPLAY_OVERSAMPLE
        if w > target_w:
            scale = target_w / float(w)
            return cv2.resize(
                gray_u8,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        return gray_u8

    def set_bgr(self, frame_bgr):
        if frame_bgr is None:
            self.setPixmap(QtGui.QPixmap())
            return
        small = self._prescale_bgr(frame_bgr)
        qimg = bgr_to_qimage(small)
        pix = QtGui.QPixmap.fromImage(qimg)
        pix = pix.scaled(
            self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.setPixmap(pix)

    def set_gray_u8(self, gray_u8):
        if gray_u8 is None:
            self.setPixmap(QtGui.QPixmap())
            return
        small = self._prescale_gray(gray_u8)
        qimg = gray_to_qimage(small)
        pix = QtGui.QPixmap.fromImage(qimg)
        pix = pix.scaled(
            self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.setPixmap(pix)
