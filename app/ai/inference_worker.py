# app/ai/inference_worker.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InferenceWorker — Qt-friendly background AI inference loop.

Lives on its own QThread. Receives frames via feed_frame() (latest-only,
older frames are dropped), runs Hailo NPU inference, emits Detection lists
to the GUI thread.
"""

import time
from typing import List, Optional

from PyQt5 import QtCore

from .hailo_inference import HailoYOLOInference, Detection


class InferenceWorker(QtCore.QObject):
    detections_ready = QtCore.pyqtSignal(list)   # List[Detection]
    status           = QtCore.pyqtSignal(str)
    fps_updated      = QtCore.pyqtSignal(float)
    started_ok       = QtCore.pyqtSignal()
    stopped          = QtCore.pyqtSignal()

    def __init__(self, hef_path: str, conf_threshold: float = 0.25):
        super().__init__()
        self.hef_path = hef_path
        self.conf_threshold = conf_threshold
        self._engine: Optional[HailoYOLOInference] = None
        self._latest_frame = None
        self._lock = QtCore.QMutex()
        self._running = False
        self._timer: Optional[QtCore.QTimer] = None
        self._fps_ema = 0.0

    # ---------- public slots (called via QueuedConnection across threads) ----------
    @QtCore.pyqtSlot()
    def start(self):
        if self._engine is not None:
            return
        try:
            self.status.emit("AI 엔진 초기화 중...")
            self._engine = HailoYOLOInference(
                self.hef_path, conf_threshold=self.conf_threshold
            )
            self._engine.start()
        except Exception as e:
            self._engine = None
            self.status.emit("AI 초기화 실패: %s" % e)
            return

        self._running = True
        self._timer = QtCore.QTimer()
        self._timer.setInterval(10)  # poll ≤100 Hz; real rate limited by infer time
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.status.emit("AI 추론 활성")
        self.started_ok.emit()

    @QtCore.pyqtSlot()
    def stop(self):
        self._running = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
            self._engine = None
        self._fps_ema = 0.0
        self.status.emit("AI 추론 정지")
        self.stopped.emit()

    @QtCore.pyqtSlot(object)
    def feed_frame(self, frame_bgr):
        """Latest-only: any pending frame is replaced."""
        self._lock.lock()
        try:
            self._latest_frame = frame_bgr
        finally:
            self._lock.unlock()

    @QtCore.pyqtSlot(float)
    def set_conf_threshold(self, conf: float):
        self.conf_threshold = float(conf)
        if self._engine is not None:
            self._engine.conf_threshold = float(conf)

    # ---------- internal ----------
    def _tick(self):
        if not self._running or self._engine is None:
            return

        # Take latest frame (atomic swap)
        self._lock.lock()
        frame = self._latest_frame
        self._latest_frame = None
        self._lock.unlock()

        if frame is None:
            return

        try:
            t0 = time.monotonic()
            dets = self._engine.infer(frame)
            dt = time.monotonic() - t0
            inst_fps = 1.0 / max(dt, 1e-3)
            self._fps_ema = (0.2 * inst_fps + 0.8 * self._fps_ema
                              if self._fps_ema > 0 else inst_fps)
            self.detections_ready.emit(dets)
            self.fps_updated.emit(self._fps_ema)
        except Exception as e:
            self.status.emit("AI 추론 오류: %s" % e)
