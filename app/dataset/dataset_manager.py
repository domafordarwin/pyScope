# app/dataset/dataset_manager.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DatasetManager — 캡처/라벨링 → COCO 누적 → YOLO export 워크플로우.

폴더 구조:
    dataset_root/
      ├── images/                    # 원본 이미지 (PNG)
      │   ├── img_20260501_193000_001.png
      │   └── ...
      ├── annotations.coco.json      # COCO 라벨
      └── yolo_export/  (export_yolo() 호출 시 생성)
          ├── images/{train,val}/
          ├── labels/{train,val}/
          ├── classes.txt
          └── data.yaml
"""

import datetime
import os
from typing import List, Optional, Tuple

import cv2

from .coco_writer import CocoDataset
from .yolo_writer import coco_to_yolo


# ---------------------------------------------------------------------
# 양파 체세포 분열 — 표준 5 클래스
# ---------------------------------------------------------------------
ONION_MITOSIS_CLASSES = [
    "interphase",   # 간기 — 분열 안 함, 핵 보임
    "prophase",     # 전기 — 염색사 응축
    "metaphase",    # 중기 — 적도판 정렬 ⭐ 가장 보기 좋음
    "anaphase",     # 후기 — 양극 분리
    "telophase",    # 말기 — 두 딸세포 형성
]

ONION_MITOSIS_KOREAN = {
    "interphase":  "간기",
    "prophase":    "전기",
    "metaphase":   "중기",
    "anaphase":    "후기",
    "telophase":   "말기",
}


# ---------------------------------------------------------------------
# DatasetManager
# ---------------------------------------------------------------------
class DatasetManager:
    """
    한 dataset 폴더의 COCO 누적 + YOLO export.

    Use::

        mgr = DatasetManager("~/RAIM_OUTPUT/dataset_onion")
        # 라벨링 후 캡처
        mgr.add_sample(frame_bgr, [
            (2, 100, 50, 80, 80),   # class_id=2 (metaphase), bbox xywh
            (1,  60, 200, 70, 70),  # class_id=1 (prophase)
        ])
        # 통계 확인
        print(mgr.stats())
        # YOLO 학습용 export
        mgr.export_yolo("~/RAIM_OUTPUT/dataset_onion/yolo_export")
    """

    COCO_FILENAME = "annotations.coco.json"
    IMAGES_SUBDIR = "images"
    DEFAULT_YOLO_SUBDIR = "yolo_export"

    def __init__(self, dataset_root: str,
                 class_names: Optional[List[str]] = None):
        self.dataset_root = os.path.expanduser(dataset_root)
        self.images_dir = os.path.join(self.dataset_root, self.IMAGES_SUBDIR)
        self.coco_path = os.path.join(self.dataset_root, self.COCO_FILENAME)
        os.makedirs(self.images_dir, exist_ok=True)

        self.dataset = CocoDataset.read(self.coco_path)
        # 새 dataset이면 클래스 초기화
        if not self.dataset.categories:
            self.dataset.set_categories(
                class_names or ONION_MITOSIS_CLASSES, "mitosis"
            )
        elif class_names:
            # 기존에 클래스 있으면 보존 (사용자 데이터 누적 방지)
            pass

    # ---------- properties ----------
    def class_names(self) -> List[str]:
        return self.dataset.class_names()

    def class_id(self, name: str) -> int:
        return self.dataset.category_id(name)

    # ---------- add ----------
    def add_sample(self, frame_bgr,
                    boxes_xywh_class: List[Tuple[int, float, float, float, float]],
                    filename_hint: str = "") -> str:
        """
        이미지 + 박스들을 dataset에 추가. 이미지를 PNG로 저장.

        boxes_xywh_class: [(class_id, x, y, w, h)] in pixels (top-left + size)
        반환: 저장된 이미지 절대 경로
        """
        h, w = frame_bgr.shape[:2]
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        suffix = ("_" + filename_hint) if filename_hint else ""
        fname = "img_%s%s.png" % (ts, suffix)
        fpath = os.path.join(self.images_dir, fname)
        cv2.imwrite(fpath, frame_bgr)

        img_id = self.dataset.add_image(fname, w, h)
        for cls_id, bx, by, bw, bh in boxes_xywh_class:
            self.dataset.add_annotation(
                img_id, int(cls_id),
                (float(bx), float(by), float(bw), float(bh)),
            )
        self.dataset.write(self.coco_path)
        return fpath

    # ---------- stats ----------
    def stats(self) -> dict:
        s = self.dataset.stats()
        s["dataset_root"] = self.dataset_root
        s["coco_path"] = self.coco_path
        return s

    # ---------- export ----------
    def export_yolo(self, output_dir: Optional[str] = None) -> dict:
        """COCO → YOLO 형식으로 export. 이미지는 복사."""
        if output_dir is None:
            output_dir = os.path.join(self.dataset_root,
                                       self.DEFAULT_YOLO_SUBDIR)
        output_dir = os.path.expanduser(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        return coco_to_yolo(
            self.coco_path, output_dir,
            image_source_dir=self.images_dir,
        )
