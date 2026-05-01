# app/ai/hailo_inference.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HailoYOLOInference — Hailo NPU YOLO inference wrapper for RAIM Scope.

Designed for the live-preview pipeline:
  * Single VDevice held for the lifetime of the engine
  * Thread-safe via QMutex-equivalent threading.Lock
  * Letterbox preprocessing, NMS-decoded output → image-coordinate Detection
  * Tested against HailoRT 5.1.1 / Hailo-10H + yolov11m_h10.hef
  * ~27 ms / frame (37 FPS) on Pi 5

Usage::

    inf = HailoYOLOInference("/usr/share/hailo-models/yolov11m_h10.hef")
    inf.start()
    try:
        detections = inf.infer(frame_bgr)
    finally:
        inf.stop()

Or as a context manager::

    with HailoYOLOInference(hef_path) as inf:
        for frame in stream:
            print(inf.infer(frame))
"""

import os
import threading
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

# Lazy import — Hailo is system-installed; degrade gracefully if absent.
try:
    import hailo_platform as hpf
    HAILO_OK = True
except Exception:
    hpf = None
    HAILO_OK = False


# COCO 80 class names (yolov11m_h10.hef and similar are trained on COCO)
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]


@dataclass
class Detection:
    """One YOLO detection in the *original* image's pixel coordinates."""
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_id: int
    class_name: str

    def to_dict(self):
        return {
            "x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2,
            "conf": self.confidence,
            "class_id": self.class_id,
            "class_name": self.class_name,
        }


# =====================================================================
# HailoYOLOInference
# =====================================================================
class HailoYOLOInference:
    """
    YOLO-style inference on a Hailo NPU.

    Lifecycle: __init__ → start() → infer() × N → stop()
    (or use as a context manager)

    The constructor only validates inputs; the heavy VDevice setup happens in
    start() so it can be deferred to a worker thread.
    """

    def __init__(
        self,
        hef_path: str,
        class_names: Optional[Sequence[str]] = None,
        conf_threshold: float = 0.25,
    ):
        if not HAILO_OK:
            raise RuntimeError(
                "hailo_platform 가 설치되지 않았습니다. "
                "Pi에서 'sudo apt install python3-h10-hailort' 확인."
            )
        if not os.path.isfile(hef_path):
            raise FileNotFoundError(hef_path)

        self.hef_path = hef_path
        self.class_names = list(class_names) if class_names else COCO_CLASSES
        self.conf_threshold = float(conf_threshold)

        self._lock = threading.Lock()
        self._vdevice = None
        self._infer_model = None
        self._configured_ctx = None
        self._configured = None
        self._bindings = None
        self._input_h = None
        self._input_w = None
        self._input_name = None
        self._output_names = []         # all model outputs
        self._output_bufs = {}          # name -> np.zeros buffer
        self._nms_output_name = None    # the one we decode

    # ---------- context manager ----------
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # ---------- lifecycle ----------
    def start(self):
        with self._lock:
            if self._configured is not None:
                return  # already started
            self._vdevice = hpf.VDevice()
            self._infer_model = self._vdevice.create_infer_model(self.hef_path)
            self._infer_model.set_batch_size(1)
            # `configure()` returns a context manager; keep its handle alive.
            self._configured_ctx = self._infer_model.configure()
            self._configured = self._configured_ctx.__enter__()
            self._bindings = self._configured.create_bindings()

            # Input — usually single
            self._input_name = self._infer_model.input_names[0]
            in_shape = list(self._infer_model.input(self._input_name).shape)
            self._input_h, self._input_w = int(in_shape[0]), int(in_shape[1])

            # Outputs — model may have multiple (segmentation models do).
            # Allocate a buffer for every output so bindings has them all,
            # then pick the NMS output for decoding.
            self._output_names = list(self._infer_model.output_names)
            self._output_bufs = {}
            for name in self._output_names:
                out_shape = list(self._infer_model.output(name).shape)
                self._output_bufs[name] = np.zeros(out_shape, dtype=np.float32)

            # Pick the output we decode as detections.
            # 우리 wrapper는 NMS 내장 모델 (yolov8_nms_postprocess 류) 만 안전 처리.
            nms_candidates = [n for n in self._output_names
                              if "nms" in n.lower()]
            if not nms_candidates:
                self._raise_unsupported_model()
            self._nms_output_name = nms_candidates[0]

    def _raise_unsupported_model(self):
        """NMS-postprocess가 없는 모델은 별도 디코더가 필요해 명시적 거부."""
        outs = ", ".join(self._output_names) if self._output_names else "(none)"
        # cleanup partial state
        try:
            if self._configured_ctx is not None:
                self._configured_ctx.__exit__(None, None, None)
        except Exception:
            pass
        try:
            if self._vdevice is not None:
                self._vdevice.release()
        except Exception:
            pass
        self._configured_ctx = None
        self._configured = None
        self._infer_model = None
        self._vdevice = None
        self._bindings = None
        raise RuntimeError(
            "이 모델은 NMS 후처리가 내장되어 있지 않아 현재 wrapper로 디코드할 수 "
            "없습니다.\n"
            "사용 가능 outputs: %s\n"
            "권장: yolov11m_h10.hef 또는 yolov8m_h10.hef 같은 "
            "NMS-postprocess 내장 모델을 선택하세요." % outs
        )

    def stop(self):
        with self._lock:
            try:
                if self._configured_ctx is not None:
                    self._configured_ctx.__exit__(None, None, None)
            except Exception:
                pass
            try:
                if self._vdevice is not None:
                    self._vdevice.release()
            except Exception:
                pass
            self._configured_ctx = None
            self._configured = None
            self._infer_model = None
            self._vdevice = None
            self._bindings = None

    # ---------- properties ----------
    @property
    def input_size(self) -> Tuple[int, int]:
        """(width, height) of the model's expected input."""
        return (self._input_w or 0, self._input_h or 0)

    @property
    def output_buffer_size(self) -> int:
        if self._nms_output_name and self._nms_output_name in self._output_bufs:
            return self._output_bufs[self._nms_output_name].size
        return 0

    @property
    def output_summary(self) -> str:
        """디버그용: 모든 output 정보 한 줄."""
        if not self._output_bufs:
            return "(no outputs)"
        parts = []
        for name in self._output_names:
            tag = "*" if name == self._nms_output_name else " "
            parts.append("%s%s[%s]" % (
                tag, name,
                "x".join(str(d) for d in self._output_bufs[name].shape)
            ))
        return ", ".join(parts)

    # ---------- inference ----------
    def infer(self, frame_bgr: np.ndarray) -> List[Detection]:
        """Run inference on one BGR frame; return detections in original coords."""
        with self._lock:
            if self._configured is None:
                raise RuntimeError("HailoYOLOInference not started")

            orig_h, orig_w = frame_bgr.shape[:2]

            # 1. Preprocess: BGR → RGB → letterbox to model input
            input_arr, scale, pad_x, pad_y = self._preprocess(frame_bgr)

            # 2. Bind all inputs/outputs by name (multi-output safe).
            #    Single-output models still work — just one binding.
            self._bindings.input(self._input_name).set_buffer(input_arr)
            for name, buf in self._output_bufs.items():
                self._bindings.output(name).set_buffer(buf)

            self._configured.run([self._bindings], 5000)

            # 3. Take NMS output (heuristically picked at start time)
            raw = self._bindings.output(self._nms_output_name).get_buffer()

            # 4. Postprocess
            return self._decode_nms(
                raw, orig_w, orig_h, scale, pad_x, pad_y
            )

    # ---------- internals ----------
    def _preprocess(self, frame_bgr):
        """BGR → RGB → letterbox resize to (input_w, input_h)."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = min(self._input_w / float(w), self._input_h / float(h))
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full(
            (self._input_h, self._input_w, 3), 114, dtype=np.uint8
        )
        pad_x = (self._input_w - nw) // 2
        pad_y = (self._input_h - nh) // 2
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        return canvas, scale, pad_x, pad_y

    def _decode_nms(self, raw, orig_w, orig_h, scale, pad_x, pad_y):
        """
        Decode Hailo NMS post-processed output.

        Hailo SDK can return NMS output in *two different formats*:

          (A) List of arrays per class (SDK 5.x default for nms_postprocess)
              raw = [class_0_dets, class_1_dets, ..., class_N_dets]
              each class_X_dets shape (num_dets, 5) — variable length per class
              Each row: [y_min, x_min, y_max, x_max, score], normalized [0,1]

          (B) Flat float32 array
              raw shape (n_classes * (1 + max_per_class * 5),)
              per class c: [count, [y_min, x_min, y_max, x_max, score] x 100]

        We branch on type. (A) must be tried first because np.asarray on a
        list of arrays with different shapes raises inhomogeneous-shape error.
        """
        # ---- (A) list of arrays per class ----
        if isinstance(raw, list):
            return self._decode_list_per_class(
                raw, orig_w, orig_h, scale, pad_x, pad_y,
            )

        # ---- (B) flat array ----
        try:
            flat = np.asarray(raw, dtype=np.float32).flatten()
        except (ValueError, TypeError):
            # numpy can't coerce — must be (A) but with mixed array depth
            try:
                return self._decode_list_per_class(
                    list(raw), orig_w, orig_h, scale, pad_x, pad_y,
                )
            except Exception:
                return []

        n_classes = len(self.class_names)
        per_class = 1 + 100 * 5

        if flat.size == n_classes * per_class:
            return self._decode_packed(
                flat.reshape(n_classes, per_class),
                orig_w, orig_h, scale, pad_x, pad_y,
            )

        if flat.size % (n_classes * 5) == 0:
            try:
                return self._decode_dense(
                    flat.reshape(n_classes, -1, 5),
                    orig_w, orig_h, scale, pad_x, pad_y,
                )
            except Exception:
                pass

        return []

    def _decode_list_per_class(self, per_class_arrays, orig_w, orig_h,
                                 scale, pad_x, pad_y):
        """
        per_class_arrays[i] = ndarray (num_dets, 5) for class i.
        Empty / None classes are skipped.
        """
        detections = []
        for class_id, class_dets in enumerate(per_class_arrays):
            if class_dets is None:
                continue
            try:
                arr = np.asarray(class_dets, dtype=np.float32)
            except Exception:
                continue
            if arr.size == 0:
                continue
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.shape[1] < 5:
                continue
            for det in arr:
                y1, x1, y2, x2, score = (float(det[0]), float(det[1]),
                                           float(det[2]), float(det[3]),
                                           float(det[4]))
                if score < self.conf_threshold:
                    continue
                detections.append(self._mk_det(
                    class_id, score, x1, y1, x2, y2,
                    orig_w, orig_h, scale, pad_x, pad_y,
                ))
        return detections

    def _decode_packed(self, arr, orig_w, orig_h, scale, pad_x, pad_y):
        """Layout: per-class [count, det0, det1, ...] with det = (y1,x1,y2,x2,score)."""
        detections = []
        n_classes = arr.shape[0]
        for c in range(n_classes):
            count = int(arr[c, 0])
            if count <= 0:
                continue
            count = min(count, 100)
            dets = arr[c, 1:1 + count * 5].reshape(count, 5)
            for det in dets:
                y1, x1, y2, x2, score = float(det[0]), float(det[1]), \
                                         float(det[2]), float(det[3]), \
                                         float(det[4])
                if score < self.conf_threshold:
                    continue
                detections.append(self._mk_det(
                    c, score, x1, y1, x2, y2,
                    orig_w, orig_h, scale, pad_x, pad_y,
                ))
        return detections

    def _decode_dense(self, arr, orig_w, orig_h, scale, pad_x, pad_y):
        """Layout: (n_classes, max_per_class, 5)."""
        detections = []
        n_classes = arr.shape[0]
        for c in range(n_classes):
            for i in range(arr.shape[1]):
                score = float(arr[c, i, 4])
                if score < self.conf_threshold:
                    continue
                y1, x1, y2, x2 = (float(arr[c, i, 0]), float(arr[c, i, 1]),
                                   float(arr[c, i, 2]), float(arr[c, i, 3]))
                detections.append(self._mk_det(
                    c, score, x1, y1, x2, y2,
                    orig_w, orig_h, scale, pad_x, pad_y,
                ))
        return detections

    def _mk_det(self, class_id, score, x1, y1, x2, y2,
                orig_w, orig_h, scale, pad_x, pad_y):
        """Convert normalized [0,1] (model input space) → original image coords."""
        # 1) denormalize to model-input pixels
        x1 *= self._input_w
        x2 *= self._input_w
        y1 *= self._input_h
        y2 *= self._input_h
        # 2) reverse letterbox padding + scale
        x1 = (x1 - pad_x) / scale
        x2 = (x2 - pad_x) / scale
        y1 = (y1 - pad_y) / scale
        y2 = (y2 - pad_y) / scale
        # 3) clip to image bounds
        x1 = max(0.0, min(orig_w - 1.0, x1))
        x2 = max(0.0, min(orig_w - 1.0, x2))
        y1 = max(0.0, min(orig_h - 1.0, y1))
        y2 = max(0.0, min(orig_h - 1.0, y2))

        cls_name = (
            self.class_names[class_id]
            if 0 <= class_id < len(self.class_names)
            else "class_%d" % class_id
        )
        return Detection(
            x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2),
            confidence=float(score),
            class_id=int(class_id),
            class_name=cls_name,
        )
