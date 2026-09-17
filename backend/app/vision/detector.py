"""Детектор предметов для фактов: кровати, столы, техника и сантехника на фото общежитий.

YOLOv10-s в формате ONNX int8 (onnx-community/yolov10s, COCO-80). Выбран вместо YOLO11s на PyTorch:
модель без NMS отдаёт готовые рамки одним тензором, веса занимают 7,6 МБ вместо 20 МБ, а torch
и ultralytics не нужны вовсе. Nano-версию проверяли тоже - она пропускает кровати на общих планах.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
from PIL import Image

from . import onnx_backend as ob

log = logging.getLogger("candid.detector")

COCO_RU = {
    59: "кровать", 60: "стол", 56: "стул", 57: "диван", 62: "телевизор/монитор", 63: "ноутбук",
    72: "холодильник", 68: "микроволновка", 69: "плита", 71: "раковина", 61: "унитаз", 73: "книга",
    0: "человек", 32: "мяч",
}
CLASSES = set(COCO_RU)
IMGSZ = 640  # граф экспортирован с фиксированным батчем 1

_lock = threading.Lock()
_session: Any = None
_io: tuple[str, str] | None = None


def get_detector() -> Any:
    global _session, _io
    if _session is None:
        with _lock:
            if _session is None:
                path = ob.ensure_file(ob.HF.format(repo=ob.DETECTOR["repo"], file=ob.DETECTOR["file"]),
                                      ob.models_dir() / ob.DETECTOR["local"])
                sess = ob.session(path)
                _io = (sess.get_inputs()[0].name, sess.get_outputs()[0].name)
                _session = sess
    return _session


def _letterbox(img: Image.Image) -> tuple[np.ndarray, float, int, int]:
    """Вписывает кадр в квадрат 640×640 с сохранением пропорций, как при обучении YOLO."""
    w, h = img.size
    r = min(IMGSZ / w, IMGSZ / h)
    nw, nh = max(1, round(w * r)), max(1, round(h * r))
    canvas = Image.new("RGB", (IMGSZ, IMGSZ), (114, 114, 114))
    canvas.paste(img.convert("RGB").resize((nw, nh), Image.BILINEAR), ((IMGSZ - nw) // 2, (IMGSZ - nh) // 2))
    a = np.asarray(canvas, dtype=np.float32) / 255.0
    return np.ascontiguousarray(a.transpose(2, 0, 1)), r, (IMGSZ - nw) // 2, (IMGSZ - nh) // 2


def detect(images: list[Image.Image], conf: float = 0.35, batch: int = 1) -> list[list[dict[str, Any]]]:
    """Рамки в долях от размера кадра: [{cls, label, conf, x, y, w, h}, ...] для каждого фото."""
    if not images:
        return []
    try:
        sess = get_detector()
    except Exception as e:  # noqa: BLE001  без детектора сервис работает, просто без фактов по предметам
        log.warning("детектор недоступен: %s", e)
        return [[] for _ in images]
    inp, outp = _io  # type: ignore[misc]
    out: list[list[dict[str, Any]]] = []
    for i in range(0, len(images), batch):
        chunk = images[i:i + batch]
        prepared = [_letterbox(im) for im in chunk]
        arr = np.stack([p[0] for p in prepared])
        raw = sess.run([outp], {inp: arr})[0]
        for j, im in enumerate(chunk):
            _, r, padx, pady = prepared[j]
            w, h = im.size
            boxes: list[dict[str, Any]] = []
            for row in np.asarray(raw[j]):
                score = float(row[4])
                cls = int(row[5])
                if score < conf or cls not in CLASSES:
                    continue
                x1 = (float(row[0]) - padx) / r
                y1 = (float(row[1]) - pady) / r
                x2 = (float(row[2]) - padx) / r
                y2 = (float(row[3]) - pady) / r
                x1, y1 = max(0.0, x1), max(0.0, y1)
                x2, y2 = min(float(w), x2), min(float(h), y2)
                if x2 - x1 < 4 or y2 - y1 < 4:
                    continue
                boxes.append({
                    "cls": cls, "label": COCO_RU.get(cls, str(cls)), "conf": round(score, 3),
                    "x": round(x1 / w, 4), "y": round(y1 / h, 4),
                    "w": round((x2 - x1) / w, 4), "h": round((y2 - y1) / h, 4),
                })
            out.append(boxes)
    return out


def warmup() -> None:
    detect([Image.new("RGB", (IMGSZ, IMGSZ), (114, 114, 114))], conf=0.9)


def info() -> dict[str, Any]:
    return {"model": f"{ob.DETECTOR['repo']} ({ob.DETECTOR['file']})", "runtime": "onnxruntime",
            "loaded": _session is not None}
