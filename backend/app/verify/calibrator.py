"""Логистический калибратор достоверности. Веса лежат в ml/calibrator_weights.json."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

WEIGHTS_PATH = Path(__file__).resolve().parents[3] / "ml" / "calibrator_weights.json"

FEATURES = ["geo", "geo_far", "text", "source", "visual", "category", "trash", "watermark"]


@lru_cache
def load() -> dict[str, Any]:
    return json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))


def predict(features: dict[str, float]) -> float:
    w = load()
    z = w["bias"] + sum(w["weights"].get(k, 0.0) * features.get(k, 0.0) for k in FEATURES)
    return 1.0 / (1.0 + math.exp(-z))


def weight(key: str) -> float:
    return load()["weights"].get(key, 0.0)


def thresholds() -> tuple[float, float]:
    t = load()["thresholds"]
    return t["high"], t["medium"]


def info() -> dict[str, Any]:
    w = load()
    return {"trained": w.get("trained", False), "note": w.get("note", ""), "samples": w.get("samples"), "metrics": w.get("metrics")}
