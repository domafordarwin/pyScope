# app/util/paths.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
from typing import Dict, Any


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def now_tag() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_pngs_recursive(root: str):
    out = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".png"):
                out.append(os.path.join(dirpath, fn))
    out.sort(key=lambda p: os.path.getmtime(p))
    return out
