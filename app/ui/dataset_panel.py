# app/ui/dataset_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DatasetPanel — 양파 체세포 분열 라벨링 + COCO/YOLO export 워크플로우.

흐름:
  1) 라이브뷰에서 ROI 드래그 → set_current_roi()로 패널에 ROI 전달
  2) 클래스 선택 + "박스 추가" → pending labels에 누적 (오버레이로 표시)
  3) 박스 여러 개 추가 후 "스냅샷 + 라벨 저장" → 이미지 + COCO 한 번에 저장
  4) 통계 확인
  5) "YOLO 형식 export" → Ultralytics 학습용 폴더 생성

시그널:
  pending_changed(list)  — 현재 누적된 박스 리스트 변경 시 (LiveView overlay용)
  capture_requested()    — main_window가 현재 frame을 받아 receive_capture()로 호출
"""

import os
from typing import List, Optional, Tuple

from PyQt5 import QtCore, QtWidgets

from .style import Color, make_separator
from ..dataset import (
    DatasetManager, ONION_MITOSIS_CLASSES, ONION_MITOSIS_KOREAN,
)


class DatasetPanel(QtWidgets.QWidget):
    pending_changed         = QtCore.pyqtSignal(list)   # [(class_id, name, x,y,w,h)]
    labels_cleared          = QtCore.pyqtSignal()
    capture_requested       = QtCore.pyqtSignal()
    status_message          = QtCore.pyqtSignal(str)
    ai_to_labels_requested  = QtCore.pyqtSignal()       # active learning

    DEFAULT_ROOT = os.path.expanduser("~/RAIM_OUTPUT/dataset_onion")

    def __init__(self, parent=None):
        super().__init__(parent)

        self._manager: Optional[DatasetManager] = None
        self._pending: List[Tuple[int, str, float, float, float, float]] = []
        self._current_roi = None  # (x,y,w,h) in image coords

        self._build_ui()
        self._init_manager(self.DEFAULT_ROOT)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- header: dataset folder ----
        head = QtWidgets.QLabel("데이터셋 라벨링  ·  양파 체세포 분열")
        head.setProperty("role", "title")
        root.addWidget(head)

        cap_root = QtWidgets.QLabel("저장 폴더")
        cap_root.setProperty("role", "caption")
        root.addWidget(cap_root)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(6)
        self.ed_root = QtWidgets.QLineEdit(self.DEFAULT_ROOT)
        self.btn_pick = QtWidgets.QPushButton("…")
        self.btn_pick.setProperty("role", "ghost")
        self.btn_pick.setFixedWidth(36)
        self.btn_pick.clicked.connect(self._pick_dataset_dir)
        self.ed_root.editingFinished.connect(
            lambda: self._init_manager(self.ed_root.text().strip())
        )
        row1.addWidget(self.ed_root, 1)
        row1.addWidget(self.btn_pick)
        root.addLayout(row1)

        root.addWidget(make_separator("h"))

        # ---- class selection ----
        cap_cls = QtWidgets.QLabel("클래스")
        cap_cls.setProperty("role", "caption")
        root.addWidget(cap_cls)

        self.cmb_class = QtWidgets.QComboBox()
        for name in ONION_MITOSIS_CLASSES:
            kr = ONION_MITOSIS_KOREAN.get(name, name)
            self.cmb_class.addItem("%s · %s" % (kr, name), userData=name)
        # default = metaphase (가장 보기 좋음)
        self.cmb_class.setCurrentIndex(2)
        root.addWidget(self.cmb_class)

        # ---- ROI status ----
        self.lbl_roi = QtWidgets.QLabel(
            "ROI: 없음 — 라이브뷰에서 드래그하세요"
        )
        self.lbl_roi.setProperty("role", "muted")
        self.lbl_roi.setWordWrap(True)
        root.addWidget(self.lbl_roi)

        # ---- add label button ----
        self.btn_add = QtWidgets.QPushButton("➕  박스 추가  (현재 ROI를 라벨로)")
        self.btn_add.setProperty("role", "primary")
        self.btn_add.setMinimumHeight(36)
        self.btn_add.clicked.connect(self._on_add_label)
        root.addWidget(self.btn_add)

        # ---- pending labels list ----
        cap_pending = QtWidgets.QLabel("현재 프레임에 추가된 박스")
        cap_pending.setProperty("role", "caption")
        root.addWidget(cap_pending)

        self.list_pending = QtWidgets.QListWidget()
        self.list_pending.setMinimumHeight(110)
        self.list_pending.setSelectionMode(
            QtWidgets.QListWidget.SingleSelection
        )
        root.addWidget(self.list_pending)

        del_row = QtWidgets.QHBoxLayout()
        del_row.setSpacing(6)
        self.btn_del = QtWidgets.QPushButton("선택 박스 삭제")
        self.btn_del.setProperty("role", "ghost")
        self.btn_del.clicked.connect(self._on_delete_selected)
        self.btn_clear = QtWidgets.QPushButton("모두 비우기")
        self.btn_clear.setProperty("role", "ghost")
        self.btn_clear.clicked.connect(self._on_clear_pending)
        del_row.addWidget(self.btn_del)
        del_row.addWidget(self.btn_clear)
        root.addLayout(del_row)

        root.addWidget(make_separator("h"))

        # ---- AI 자동 라벨링 (active learning) ----
        self.btn_ai_labels = QtWidgets.QPushButton(
            "🤖  AI 검출 결과를 라벨로  (active learning)"
        )
        self.btn_ai_labels.setProperty("role", "ghost")
        self.btn_ai_labels.setMinimumHeight(32)
        self.btn_ai_labels.setToolTip(
            "현재 검출 탭의 AI 추론 결과를 모두 pending 박스로 추가합니다.\n"
            "검토 후 ‘스냅샷 + 라벨 저장’으로 데이터셋에 영구 저장하세요.\n"
            "(AI 검출 클래스가 우리 클래스에 있는 경우만 추가됨)"
        )
        self.btn_ai_labels.clicked.connect(self.ai_to_labels_requested.emit)
        root.addWidget(self.btn_ai_labels)

        # ---- save / export ----
        self.btn_save = QtWidgets.QPushButton(
            "💾  스냅샷 + 라벨 저장  (현재 프레임)"
        )
        self.btn_save.setProperty("role", "success")
        self.btn_save.setMinimumHeight(38)
        self.btn_save.clicked.connect(self._on_request_capture)
        root.addWidget(self.btn_save)

        self.btn_export = QtWidgets.QPushButton("📦  YOLO 형식으로 export (train/val 자동 분할)")
        self.btn_export.setProperty("role", "ghost")
        self.btn_export.setMinimumHeight(32)
        self.btn_export.clicked.connect(self._on_export_yolo)
        root.addWidget(self.btn_export)

        root.addWidget(make_separator("h"))

        # ---- statistics ----
        cap_stats = QtWidgets.QLabel("데이터셋 통계")
        cap_stats.setProperty("role", "caption")
        root.addWidget(cap_stats)

        self.lbl_stats = QtWidgets.QLabel("(불러오는 중...)")
        self.lbl_stats.setProperty("role", "muted")
        self.lbl_stats.setWordWrap(True)
        root.addWidget(self.lbl_stats)

        root.addStretch(1)

    # ---------------------------------------------------------------- Manager
    def _init_manager(self, root_path: str):
        try:
            self._manager = DatasetManager(root_path)
            self.status_message.emit(
                "데이터셋 폴더: %s" % self._manager.dataset_root
            )
            self._refresh_stats()
        except Exception as e:
            self.lbl_stats.setText("초기화 실패: %s" % e)
            self.status_message.emit("데이터셋 초기화 실패: %s" % e)

    def _pick_dataset_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "데이터셋 폴더 선택", self.ed_root.text().strip()
        )
        if d:
            self.ed_root.setText(d)
            self._init_manager(d)

    def _refresh_stats(self):
        if self._manager is None:
            return
        s = self._manager.stats()
        lines = [
            "이미지: %d장" % s["n_images"],
            "라벨: %d개" % s["n_annotations"],
        ]
        if s["per_class"]:
            lines.append("클래스별:")
            for name, n in sorted(s["per_class"].items(),
                                    key=lambda x: -x[1]):
                kr = ONION_MITOSIS_KOREAN.get(name, name)
                lines.append("  • %s (%s) : %d" % (kr, name, n))
        self.lbl_stats.setText("\n".join(lines))

    # ---------------------------------------------------------------- ROI
    @QtCore.pyqtSlot(object)
    def set_current_roi(self, roi_xywh):
        """LiveView roi_changed 시그널 → 이 슬롯."""
        self._current_roi = roi_xywh
        if roi_xywh:
            x, y, w, h = roi_xywh
            self.lbl_roi.setText(
                "ROI: x=%d y=%d  %d×%d 픽셀" % (x, y, w, h)
            )
        else:
            self.lbl_roi.setText("ROI: 없음 — 라이브뷰에서 드래그하세요")

    # ---------------------------------------------------------------- Pending
    def _on_add_label(self):
        if not self._current_roi:
            self.status_message.emit("먼저 라이브뷰에서 ROI를 드래그하세요")
            return
        if self._manager is None:
            self.status_message.emit("데이터셋이 초기화되지 않았습니다")
            return
        cls_name = self.cmb_class.currentData()
        cls_id = self._manager.class_id(cls_name)
        if cls_id < 0:
            self.status_message.emit("알 수 없는 클래스: %s" % cls_name)
            return
        x, y, w, h = self._current_roi
        self._pending.append((cls_id, cls_name, float(x), float(y),
                                float(w), float(h)))
        self._refresh_pending_list()
        self.pending_changed.emit(list(self._pending))
        self.status_message.emit(
            "박스 추가: %s (총 %d개)" %
            (ONION_MITOSIS_KOREAN.get(cls_name, cls_name), len(self._pending))
        )

    def _on_delete_selected(self):
        row = self.list_pending.currentRow()
        if 0 <= row < len(self._pending):
            del self._pending[row]
            self._refresh_pending_list()
            self.pending_changed.emit(list(self._pending))

    def _on_clear_pending(self):
        if not self._pending:
            return
        self._pending.clear()
        self._refresh_pending_list()
        self.pending_changed.emit([])

    def _refresh_pending_list(self):
        self.list_pending.clear()
        for cls_id, cls_name, x, y, w, h in self._pending:
            kr = ONION_MITOSIS_KOREAN.get(cls_name, cls_name)
            text = "%s · %s    [%d, %d, %d×%d]" % (
                kr, cls_name, int(x), int(y), int(w), int(h)
            )
            self.list_pending.addItem(text)

    # ---------------------------------------------------------------- Capture
    def _on_request_capture(self):
        if not self._pending:
            self.status_message.emit("저장할 박스가 없습니다 (먼저 추가)")
            return
        if self._manager is None:
            return
        # main_window에 현재 frame 요청 → receive_capture로 응답
        self.capture_requested.emit()

    @QtCore.pyqtSlot(list)
    def receive_ai_detections(self, detections):
        """
        Active learning — main_window가 현재 AI 검출 결과를 전달.
        우리 클래스에 매칭되는 검출만 pending 에 추가.
        """
        if self._manager is None:
            self.status_message.emit("데이터셋 미초기화")
            return
        if not detections:
            self.status_message.emit(
                "AI 검출 결과 없음 — 검출 탭에서 AI 활성화 후 시도"
            )
            return
        added = 0
        skipped = 0
        for det in detections:
            cls_id = self._manager.class_id(det.class_name)
            if cls_id < 0:
                skipped += 1
                continue
            w = float(det.x2) - float(det.x1)
            h = float(det.y2) - float(det.y1)
            if w < 5 or h < 5:
                continue
            self._pending.append((cls_id, det.class_name,
                                    float(det.x1), float(det.y1), w, h))
            added += 1
        self._refresh_pending_list()
        self.pending_changed.emit(list(self._pending))
        msg = "AI 라벨 %d개 추가됨" % added
        if skipped:
            msg += " (클래스 미매칭 %d개 제외)" % skipped
        self.status_message.emit(msg)

    @QtCore.pyqtSlot(object)
    def receive_capture_frame(self, frame_bgr):
        """main_window가 현재 카메라 frame을 전달."""
        if frame_bgr is None:
            self.status_message.emit("저장 실패: 카메라 frame 없음")
            return
        if self._manager is None or not self._pending:
            return
        boxes = [(cid, x, y, w, h)
                  for cid, _name, x, y, w, h in self._pending]
        try:
            path = self._manager.add_sample(frame_bgr, boxes)
            self.status_message.emit("저장됨: %s (%d 박스)" %
                                       (os.path.basename(path), len(boxes)))
            self._on_clear_pending()
            self._refresh_stats()
        except Exception as e:
            self.status_message.emit("저장 실패: %s" % e)

    # ---------------------------------------------------------------- Export
    def _on_export_yolo(self):
        if self._manager is None:
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "YOLO 형식 export 폴더 선택",
            os.path.dirname(self._manager.dataset_root) or os.path.expanduser("~"),
        )
        if not out_dir:
            return
        try:
            result = self._manager.export_yolo(out_dir)
            n_train = result.get("n_train", result["n_images"])
            n_val = result.get("n_val", 0)
            self.status_message.emit(
                "YOLO export 완료: train %d · val %d · %d 라벨 · %d 클래스" %
                (n_train, n_val, result["n_annotations"], result["n_classes"])
            )
            QtWidgets.QMessageBox.information(
                self, "YOLO Export 완료",
                "Train: %d 이미지\nVal:   %d 이미지\n라벨:  %d개\n클래스: %d\n\n"
                "경로: %s\n\n"
                "Ultralytics 학습 명령:\n"
                "  yolo detect train \\\n"
                "    data=%s/data.yaml \\\n"
                "    model=yolov8n.pt \\\n"
                "    imgsz=640 epochs=100 batch=16\n\n"
                "ONNX export:\n"
                "  yolo export model=runs/detect/train/weights/best.pt "
                "format=onnx imgsz=640" % (
                    n_train, n_val, result["n_annotations"],
                    result["n_classes"], result["output_dir"],
                    result["output_dir"],
                ),
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "YOLO Export 실패", str(e)
            )
