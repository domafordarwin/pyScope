# app/ai/__init__.py
"""Hailo NPU AI inference for RAIM Scope."""

from .hailo_inference import HailoYOLOInference, Detection, COCO_CLASSES, HAILO_OK

__all__ = ["HailoYOLOInference", "Detection", "COCO_CLASSES", "HAILO_OK"]
