# app/capture/capture_controller.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import cv2
import time
from PyQt5 import QtCore
from typing import Optional, Dict, Any

from ..util.paths import ensure_dir, now_tag, write_json
from ..util.image_convert import crop_bgr
from ..imaging.dpc import dpc_from_pair, dpc_to_u8, bf_to_u8
from ..imaging.rgb_compose import pseudo_rgb


class CaptureController(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    saved = QtCore.pyqtSignal(str)          # saved image path
    dpc_updated = QtCore.pyqtSignal(object) # dict with bf_u8/dpcx_u8/dpcy_u8/pseudo_bgr

    def __init__(self, sense_panel=None):
        super().__init__()
        self.sense_panel = sense_panel

        self.output_dir = ensure_dir(os.path.expanduser("~/RAIM_OUTPUT"))
        self.seq_dir = ""

        self._last_frame = None
        self._last_roi_xywh = None

        # DPC capture state machine
        self._dpc_busy = False
        self._dpc_stage = ""
        self._stage_deadline = 0.0

        self._frame_left = None
        self._frame_right = None
        self._frame_top = None
        self._frame_bottom = None
        self._frame_bf = None

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)

        # outputs cache
        self.bf_u8 = None
        self.dpcx_u8 = None
        self.dpcy_u8 = None
        self.pseudo_bgr = None

    def set_output_dir(self, path: str):
        self.output_dir = ensure_dir(path)
        self.status.emit(f"Output dir: {self.output_dir}")

    def new_sequence(self, name: str):
        tag = now_tag()
        safe = "".join([c for c in name.strip() if c.isalnum() or c in ("-", "_")])
        if not safe:
            safe = "default"
        self.seq_dir = ensure_dir(os.path.join(self.output_dir, f"SEQ_{tag}_{safe}"))
        self.status.emit(f"New sequence: {self.seq_dir}")

    def update_roi(self, roi_xywh):
        self._last_roi_xywh = roi_xywh

    def on_frame(self, frame_bgr):
        self._last_frame = frame_bgr
        # stage wants first fresh frame after LED pattern changed
        if self._dpc_busy and self._dpc_stage and time.time() >= self._stage_deadline:
            self._consume_stage_frame(frame_bgr)

    # ---------- Snapshot Save ----------
    def save_snapshot(self, kind: str, image_bgr_or_gray_u8, meta_extra: Optional[Dict[str, Any]] = None):
        if image_bgr_or_gray_u8 is None:
            self.status.emit("Snapshot failed: no image")
            return

        if not self.seq_dir:
            self.new_sequence("default")

        tag = now_tag()
        base = f"{tag}_{kind}"
        img_path = os.path.join(self.seq_dir, f"{base}.png")
        meta_path = os.path.join(self.seq_dir, f"{base}.json")

        # ensure u8
        img = image_bgr_or_gray_u8
        if img.ndim == 2:
            cv2.imwrite(img_path, img)
        else:
            cv2.imwrite(img_path, img)

        meta = {
            "timestamp": tag,
            "kind": kind,
            "roi_xywh": self._last_roi_xywh,
            "frame_shape": None if self._last_frame is None else list(self._last_frame.shape),
            "led": self._sense_meta(),
        }
        if meta_extra:
            meta.update(meta_extra)

        write_json(meta_path, meta)
        self.status.emit(f"Saved: {img_path}")
        self.saved.emit(img_path)

    def _sense_meta(self):
        if self.sense_panel is None:
            return {"available": False}
        return {
            "available": True,
            "rgb": list(self.sense_panel.get_color()),
            "brightness": int(self.sense_panel.get_brightness()),
            "effective_rgb": list(self.sense_panel.effective_rgb()),
            "pattern_name": self.sense_panel.current_pattern_name(),
            "grid_on": self.sense_panel.get_grid_state_flat(),
        }

    # ---------- DPC Capture Flow ----------
    def start_dpc_capture(self, include_bf=True):
        if self._dpc_busy:
            self.status.emit("DPC capture busy")
            return
        if self.sense_panel is None:
            self.status.emit("Sense panel not connected")
            return
        if self._last_frame is None:
            self.status.emit("No camera frame yet")
            return

        self._dpc_busy = True
        self._frame_left = None
        self._frame_right = None
        self._frame_top = None
        self._frame_bottom = None
        self._frame_bf = None
        self._want_bf = bool(include_bf)

        self.status.emit("DPC capture: starting")
        self._timer.start()
        self._set_stage("left")

    def _tick(self):
        # (nothing heavy here; frames are captured in on_frame)
        if not self._dpc_busy:
            self._timer.stop()

    def _set_stage(self, stage: str):
        self._dpc_stage = stage
        # allow LED settle + camera latency: capture frame after a short delay
        self._stage_deadline = time.time() + 0.12

        if stage == "left":
            self.sense_panel.apply_preset("DPC_LEFT")
            self.status.emit("DPC: set LEFT illumination")
        elif stage == "right":
            self.sense_panel.apply_preset("DPC_RIGHT")
            self.status.emit("DPC: set RIGHT illumination")
        elif stage == "top":
            self.sense_panel.apply_preset("DPC_TOP")
            self.status.emit("DPC: set TOP illumination")
        elif stage == "bottom":
            self.sense_panel.apply_preset("DPC_BOTTOM")
            self.status.emit("DPC: set BOTTOM illumination")
        elif stage == "bf":
            self.sense_panel.apply_preset("BF")
            self.status.emit("DPC: set BF illumination")
        elif stage == "done":
            self._finish_dpc()
        else:
            self.status.emit(f"Unknown stage: {stage}")
            self._abort_dpc()

    def _consume_stage_frame(self, frame_bgr):
        # capture ROI-cropped for all modalities
        roi = self._last_roi_xywh
        fr = crop_bgr(frame_bgr, roi) if roi else frame_bgr.copy()

        stage = self._dpc_stage
        self._dpc_stage = ""  # consume once
        if stage == "left":
            self._frame_left = fr
            self._set_stage("right")
        elif stage == "right":
            self._frame_right = fr
            self._set_stage("top")
        elif stage == "top":
            self._frame_top = fr
            self._set_stage("bottom")
        elif stage == "bottom":
            self._frame_bottom = fr
            if self._want_bf:
                self._set_stage("bf")
            else:
                self._set_stage("done")
        elif stage == "bf":
            self._frame_bf = fr
            self._set_stage("done")

    def _finish_dpc(self):
        # compute dpc
        dpcx = dpc_from_pair(self._frame_left, self._frame_right)
        dpcy = dpc_from_pair(self._frame_top, self._frame_bottom)
        self.dpcx_u8 = dpc_to_u8(dpcx)
        self.dpcy_u8 = dpc_to_u8(dpcy)

        if self._frame_bf is not None:
            self.bf_u8 = bf_to_u8(self._frame_bf)
        else:
            # fallback: use last frame as BF
            self.bf_u8 = bf_to_u8(self._last_frame)

        self.pseudo_bgr = pseudo_rgb(self.dpcx_u8, self.bf_u8, self.dpcy_u8)

        self.dpc_updated.emit({
            "bf_u8": self.bf_u8,
            "dpcx_u8": self.dpcx_u8,
            "dpcy_u8": self.dpcy_u8,
            "pseudo_bgr": self.pseudo_bgr,
        })

        self._dpc_busy = False
        self._timer.stop()
        self.status.emit("DPC capture: done")

    def _abort_dpc(self):
        self._dpc_busy = False
        self._timer.stop()
        self.status.emit("DPC capture: aborted")
