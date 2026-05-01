# app/util/image_convert.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cv2
import numpy as np
from PyQt5 import QtGui


def bgr_to_qimage(frame_bgr):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    return QtGui.QImage(rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888).copy()


def gray_to_qimage(gray_u8):
    if gray_u8.ndim == 3:
        gray_u8 = cv2.cvtColor(gray_u8, cv2.COLOR_BGR2GRAY)
    h, w = gray_u8.shape[:2]
    bytes_per_line = w
    return QtGui.QImage(gray_u8.data, w, h, bytes_per_line, QtGui.QImage.Format_Grayscale8).copy()


def crop_bgr(frame_bgr, roi_xywh):
    if frame_bgr is None or roi_xywh is None:
        return None
    x, y, w, h = roi_xywh
    x = max(0, int(x)); y = max(0, int(y))
    w = max(1, int(w)); h = max(1, int(h))
    H, W = frame_bgr.shape[:2]
    x2 = min(W, x + w)
    y2 = min(H, y + h)
    if x >= x2 or y >= y2:
        return None
    return frame_bgr[y:y2, x:x2].copy()


def normalize_to_u8(img, clip_percentile=0.5):
    """
    img: float or int array
    percentile clipping + normalize to 0..255
    """
    arr = img.astype(np.float32)
    lo = np.percentile(arr, clip_percentile)
    hi = np.percentile(arr, 100.0 - clip_percentile)
    if hi - lo < 1e-6:
        hi = lo + 1.0
    arr = (arr - lo) / (hi - lo)
    arr = np.clip(arr, 0.0, 1.0)
    return (arr * 255.0).astype(np.uint8)
