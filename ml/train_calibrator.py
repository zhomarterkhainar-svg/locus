"""Обучение калибратора достоверности на размеченных фото.

Разметка: выгрузите признаки собранного профиля
  curl -o data/labels/Q127745.jsonl http://localhost:8000/api/profile/Q127745/features.jsonl
и в каждой строке поставьте "label": 1 (фото относится к вузу и разделу) или 0 (не относится).
Строки с label = null пропускаются.

python ml/train_calibrator.py data/labels/*.jsonl
Скрипт делает 5-кратную кросс-валидацию, печатает точность, Brier и ECE,
и записывает веса в ml/calibrator_weights.json с пометкой trained = true.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ["geo", "geo_far", "text", "source", "visual", "category", "trash", "watermark"]
OUT = ROOT / "ml" / "calibrator_weights.json"


def load(paths: list[str]) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("label") not in (0, 1):
                continue
            f = row["features"]
            geo = f.get("geo", 0.0)
            xs.append([max(geo, 0.0), 1.0 if geo < 0 else 0.0, f.get("text", 0), f.get("source", 0), f.get("visual", 0),
                       f.get("category", 0), f.get("trash", 0), f.get("watermark", 0)])
            ys.append(row["label"])
    return np.array(xs, dtype=float), np.array(ys, dtype=float)


def fit(x: np.ndarray, y: np.ndarray, l2: float = 0.05, lr: float = 0.3, epochs: int = 4000) -> tuple[np.ndarray, float]:
    w = np.zeros(x.shape[1])
    b = 0.0
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-(x @ w + b)))
        g = p - y
        w -= lr * (x.T @ g / len(y) + l2 * w)
        b -= lr * g.mean()
    return w, b


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.any():
            total += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(total)


def main(paths: list[str]) -> None:
    x, y = load(paths)
    if len(y) < 40:
        sys.exit(f"Мало размеченных строк: {len(y)}. Нужно хотя бы 40, лучше 300+.")
    rng = np.random.default_rng(7)
    idx = rng.permutation(len(y))
    folds = np.array_split(idx, 5)
    probs = np.zeros(len(y))
    for k in range(5):
        test = folds[k]
        train = np.concatenate([folds[j] for j in range(5) if j != k])
        w, b = fit(x[train], y[train])
        probs[test] = 1 / (1 + np.exp(-(x[test] @ w + b)))
    acc = float(((probs >= 0.5) == y).mean())
    brier = float(((probs - y) ** 2).mean())
    high = probs >= 0.75
    precision_high = float(y[high].mean()) if high.any() else None
    metrics = {"cv_accuracy": round(acc, 3), "cv_brier": round(brier, 3), "cv_ece": round(ece(probs, y), 3),
               "cv_precision_at_0_75": None if precision_high is None else round(precision_high, 3),
               "share_at_0_75": round(float(high.mean()), 3)}
    w, b = fit(x, y)
    current = json.loads(OUT.read_text(encoding="utf-8"))
    current.update({
        "trained": True,
        "note": f"Обучено на {len(y)} размеченных фото, 5-кратная кросс-валидация.",
        "samples": int(len(y)),
        "metrics": metrics,
        "bias": round(float(b), 4),
        "weights": {k: round(float(v), 4) for k, v in zip(FEATURES, w)},
    })
    OUT.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"веса записаны в {OUT}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
