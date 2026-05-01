# app/capture/sequence_repo.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
from typing import List, Dict
from ..util.paths import ensure_dir, list_pngs_recursive


_SEQ_RE = re.compile(r"^SEQ_\d{8}_\d{6}_.+$")


def ensure_output_dir(path: str) -> str:
    return ensure_dir(path)


def list_all_images(output_dir: str) -> List[str]:
    output_dir = ensure_output_dir(output_dir)
    return list_pngs_recursive(output_dir)


def list_sequences(output_dir: str) -> List[str]:
    output_dir = ensure_output_dir(output_dir)
    seqs = []
    for name in os.listdir(output_dir):
        p = os.path.join(output_dir, name)
        if os.path.isdir(p) and _SEQ_RE.match(name):
            seqs.append(p)
    seqs.sort(key=lambda p: os.path.getmtime(p))
    return seqs


def list_sequence_images(seq_dir: str) -> List[str]:
    if not seq_dir or not os.path.isdir(seq_dir):
        return []
    imgs = []
    for fn in os.listdir(seq_dir):
        if fn.lower().endswith(".png"):
            imgs.append(os.path.join(seq_dir, fn))
    imgs.sort()
    return imgs


def guess_seq_dir_from_image(image_path: str) -> str:
    if not image_path:
        return ""
    return os.path.dirname(image_path)


def make_thumb_label(path: str) -> str:
    base = os.path.basename(path)
    return base
