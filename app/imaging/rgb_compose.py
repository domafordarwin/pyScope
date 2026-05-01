# app/imaging/rgb_compose.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np
import cv2


def pseudo_rgb(dpcx_u8, bf_u8, dpcy_u8):
    """
    pseudo-RGB 합성:
      R = DPCx
      G = BF
      B = DPCy
    """
    if dpcx_u8 is None or bf_u8 is None or dpcy_u8 is None:
        return None

    def to_gray(x):
        if x.ndim == 3:
            return cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)
        return x

    r = to_gray(dpcx_u8)
    g = to_gray(bf_u8)
    b = to_gray(dpcy_u8)

    h = min(r.shape[0], g.shape[0], b.shape[0])
    w = min(r.shape[1], g.shape[1], b.shape[1])
    r = r[:h, :w]
    g = g[:h, :w]
    b = b[:h, :w]

    rgb = np.dstack([r, g, b]).astype(np.uint8)  # RGB
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr
