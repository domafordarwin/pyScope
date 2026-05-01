# app/dataset/coco_writer.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CocoDataset — COCO JSON 형식 dataset 누적 + load/save.

COCO format reference: https://cocodataset.org/#format-data
  bbox = [x_min, y_min, width, height]  (top-left + size, in pixels)
"""

import datetime
import json
import os
from typing import List, Optional, Tuple


class CocoDataset:
    """COCO 형식 detection dataset — 누적 추가 + JSON 저장/로드."""

    def __init__(self, description: str = "RAIM Scope dataset",
                 contributor: str = "RAIM Scope"):
        now = datetime.datetime.now()
        self.info = {
            "description": description,
            "version": "1.0",
            "year": now.year,
            "contributor": contributor,
            "date_created": now.isoformat(timespec="seconds"),
        }
        self.licenses = [{
            "id": 1,
            "name": "CC-BY-4.0",
            "url": "https://creativecommons.org/licenses/by/4.0/",
        }]
        self.categories: List[dict] = []
        self.images: List[dict] = []
        self.annotations: List[dict] = []
        self._next_image_id = 1
        self._next_ann_id = 1
        self._cat_name_to_id = {}

    # ---------- categories ----------
    def set_categories(self, names: List[str], supercategory: str = "object"):
        self.categories = []
        self._cat_name_to_id = {}
        for i, name in enumerate(names):
            cat = {"id": i, "name": name, "supercategory": supercategory}
            self.categories.append(cat)
            self._cat_name_to_id[name] = i

    def category_id(self, name: str) -> int:
        return self._cat_name_to_id.get(name, -1)

    def class_names(self) -> List[str]:
        return [c["name"] for c in
                sorted(self.categories, key=lambda c: c["id"])]

    # ---------- images / annotations ----------
    def add_image(self, file_name: str, width: int, height: int) -> int:
        img_id = self._next_image_id
        self._next_image_id += 1
        self.images.append({
            "id": img_id,
            "file_name": file_name,
            "width": int(width),
            "height": int(height),
            "date_captured": datetime.datetime.now()
                .isoformat(timespec="seconds"),
            "license": 1,
        })
        return img_id

    def add_annotation(self, image_id: int, category_id: int,
                        bbox_xywh: Tuple[float, float, float, float],
                        segmentation: Optional[list] = None) -> int:
        x, y, w, h = bbox_xywh
        ann_id = self._next_ann_id
        self._next_ann_id += 1
        self.annotations.append({
            "id": ann_id,
            "image_id": int(image_id),
            "category_id": int(category_id),
            "bbox": [float(x), float(y), float(w), float(h)],
            "area": float(w) * float(h),
            "iscrowd": 0,
            "segmentation": segmentation or [],
        })
        return ann_id

    def remove_image(self, image_id: int):
        """이미지 + 연관 annotations 모두 제거."""
        self.images = [i for i in self.images if i["id"] != image_id]
        self.annotations = [a for a in self.annotations
                             if a["image_id"] != image_id]

    # ---------- IO ----------
    def to_dict(self) -> dict:
        return {
            "info": self.info,
            "licenses": self.licenses,
            "categories": self.categories,
            "images": self.images,
            "annotations": self.annotations,
        }

    def write(self, path: str):
        """JSON 파일로 저장 (UTF-8)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def read(cls, path: str) -> "CocoDataset":
        """기존 JSON 로드 (이어쓰기). 파일 없으면 빈 dataset 반환."""
        ds = cls()
        if not os.path.isfile(path):
            return ds
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return ds

        ds.info = data.get("info", ds.info)
        ds.licenses = data.get("licenses", ds.licenses)
        ds.categories = data.get("categories", [])
        ds._cat_name_to_id = {c["name"]: c["id"] for c in ds.categories}
        ds.images = data.get("images", [])
        ds.annotations = data.get("annotations", [])
        ds._next_image_id = (max((i["id"] for i in ds.images), default=0) + 1)
        ds._next_ann_id = (max((a["id"] for a in ds.annotations), default=0) + 1)
        return ds

    # ---------- stats ----------
    def stats(self) -> dict:
        per_class = {}
        for ann in self.annotations:
            cid = ann["category_id"]
            per_class[cid] = per_class.get(cid, 0) + 1
        names = self.class_names()
        return {
            "n_images": len(self.images),
            "n_annotations": len(self.annotations),
            "per_class": {
                (names[c] if c < len(names) else "class_%d" % c): n
                for c, n in per_class.items()
            },
        }
