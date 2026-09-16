"""Обученные линейные головы поверх эмбеддингов CLIP.

Головы обучаются скриптом ml/train_heads.py на открытых размеченных фото (Wikimedia Commons, Places365)
и лежат в ml/heads/*.json (текстом, чтобы репозиторий и Space на Hugging Face обходились без LFS). Каждая голова знает, для какой модели CLIP она обучена: при несовпадении
она не загружается, и сервис работает на zero-shot промптах. Итоговая вероятность — смесь головы и
zero-shot с весом alpha, подобранным на валидации.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import get_settings

log = logging.getLogger("candid.heads")


@dataclass
class Head:
    name: str
    keys: list[str]
    W: np.ndarray  # (k, d)
    b: np.ndarray  # (k,)
    alpha: float  # доля головы в смеси с zero-shot
    metrics: dict[str, Any]

    def proba(self, emb: np.ndarray) -> np.ndarray:
        z = emb @ self.W.T + self.b
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=1, keepdims=True)

    def blend(self, emb: np.ndarray, zero_shot: np.ndarray, zs_keys: list[str]) -> np.ndarray:
        """Смешивает с zero-shot вероятностями, переставляя столбцы головы под порядок zero-shot."""
        idx = [self.keys.index(k) if k in self.keys else -1 for k in zs_keys]
        head = self.proba(emb)
        aligned = np.stack([head[:, i] if i >= 0 else zero_shot[:, j] for j, i in enumerate(idx)], axis=1)
        out = self.alpha * aligned + (1 - self.alpha) * zero_shot
        return out / out.sum(axis=1, keepdims=True)


def heads_dir() -> Path:
    s = get_settings()
    return s.path(s.heads_dir)


def load_heads(model_id: str) -> dict[str, Head]:
    d = heads_dir()
    meta_path = d / "heads.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except ValueError:
        log.warning("heads.json повреждён")
        return {}
    if meta.get("model") != model_id:
        log.warning("головы обучены для %s, а загружена %s: используется zero-shot", meta.get("model"), model_id)
        return {}
    out: dict[str, Head] = {}
    for name, info in meta.get("heads", {}).items():
        path = d / f"{name}.json"
        if not path.exists():
            continue
        try:
            z = json.loads(path.read_text(encoding="utf-8"))
            W = np.array(z["W"], dtype=np.float32)
            b = np.array(z["b"], dtype=np.float32)
            if W.shape != (len(z["keys"]), W.shape[1]) or b.shape != (len(z["keys"]),):
                raise ValueError("размеры весов не совпадают с классами")
            out[name] = Head(name=name, keys=[str(k) for k in z["keys"]], W=W, b=b,
                             alpha=float(info.get("alpha", 0.5)), metrics=info.get("metrics", {}))
        except Exception as e:  # noqa: BLE001
            log.warning("голова %s не загрузилась: %s", name, e)
    return out


def info() -> dict[str, Any]:
    p = heads_dir() / "heads.json"
    if not p.exists():
        return {"trained": False, "note": "Обученных голов нет, классификация zero-shot."}
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {"trained": False, "note": "heads.json повреждён"}
    return {"trained": True, "model": meta.get("model"), "trained_at": meta.get("trained_at"),
            "dataset": meta.get("dataset"), "heads": {k: {"alpha": v.get("alpha"), "metrics": v.get("metrics")} for k, v in meta.get("heads", {}).items()}}
