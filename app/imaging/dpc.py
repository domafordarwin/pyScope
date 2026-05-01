# app/imaging/dpc.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cv2
import numpy as np
from ..util.image_convert import normalize_to_u8


def to_gray_f32(frame_bgr):
    if frame_bgr is None:
        return None
    g = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return g.astype(np.float32)


def dpc_from_pair(a_bgr, b_bgr, eps=1e-6):
    """
    DPC = (B - A) / (B + A)
    (예: A=left illumination, B=right illumination)
    """
    A = to_gray_f32(a_bgr)
    B = to_gray_f32(b_bgr)
    if A is None or B is None:
        return None
    num = (B - A)
    den = (B + A) + eps
    dpc = num / den
    return dpc


def dpc_to_u8(dpc_float):
    if dpc_float is None:
        return None
    return normalize_to_u8(dpc_float, clip_percentile=1.0)


def bf_to_u8(bf_bgr):
    if bf_bgr is None:
        return None
    g = cv2.cvtColor(bf_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return normalize_to_u8(g, clip_percentile=0.5)
