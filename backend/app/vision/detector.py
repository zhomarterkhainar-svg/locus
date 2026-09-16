"""YOLO (COCO) для фактов: кровати, столы, стулья, кухонная и сантехническая техника на фото."""
from __future__ import annotations

import threading
from typing import Any

from ..config import get_settings

COCO_RU = {
    59: "кровать", 60: "стол", 56: "стул", 57: "диван", 62: "телевизор/монитор", 63: "ноутбук",
    72: "холодильник", 68: "микроволновка", 69: "плита", 71: "раковина", 61: "унитаз", 73: "книга",
    0: "человек", 32: "мяч",
}
CLASSES = list(COCO_RU)

_lock = threading.Lock()
_model = None


def get_detector():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from ultralytics import YOLO

                s = get_settings()
                _model = YOLO(str(s.path(s.yolo_weights)))
    return _model


def detect(images: list, conf: float = 0.35) -> list[list[dict[str, Any]]]:
    if not images:
        return []
    model = get_detector()
    results = model.predict(images, conf=conf, classes=CLASSES, verbose=False, imgsz=640, device="cpu")
    out: list[list[dict[str, Any]]] = []
    for img, res in zip(images, results):
        w, h = img.size
        boxes = []
        for b in res.boxes:
            cls = int(b.cls.item())
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
            boxes.append({
                "cls": cls, "label": COCO_RU.get(cls, str(cls)), "conf": round(float(b.conf.item()), 3),
                "x": round(x1 / w, 4), "y": round(y1 / h, 4), "w": round((x2 - x1) / w, 4), "h": round((y2 - y1) / h, 4),
            })
        out.append(boxes)
    return out
