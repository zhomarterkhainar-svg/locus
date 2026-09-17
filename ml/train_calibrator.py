"""Обучение калибратора достоверности (логистическая регрессия по сигналам принадлежности).

Данные (JSONL, строка = фото-кандидат для вуза):
- data/labels/weak_commons.jsonl — слабая разметка по категориям Commons (ml/build_calibrator_data.py);
- ручная разметка: выгрузка GET /api/profile/{QID}/features.jsonl с проставленным "label" 0/1;
- отметки пользователей «не тот вуз» из /api/feedback (label 0).
Ручные строки весят больше слабых (--human-weight).

Оценка: кросс-валидация по вузам (фото одного вуза не попадают одновременно в обучение и проверку):
точность, Brier, ECE, точность среди фото выше порога «подтверждено». Порог «подтверждено» подбирается
так, чтобы точность выше него по кросс-валидации была не ниже --target-precision.

python ml/train_calibrator.py data/labels/*.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ["geo", "geo_far", "text", "source", "visual", "category", "trash", "watermark"]
OUT = ROOT / "ml" / "calibrator_weights.json"


def row_features(f: dict) -> list[float]:
    geo = float(f.get("geo", 0.0))
    return [max(geo, 0.0), 1.0 if geo < 0 else float(f.get("geo_far", 0.0)), f.get("text", 0), f.get("source", 0),
            f.get("visual", 0), f.get("category", 0), f.get("trash", 0), f.get("watermark", 0)]


def load(paths: list[str], human_weight: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Counter]:
    xs, ys, ws, groups = [], [], [], []
    stats: Counter = Counter()
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("label") not in (0, 1) or not row.get("features"):
                continue
            weak = bool(row.get("weak"))
            xs.append(row_features(row["features"]))
            ys.append(row["label"])
            ws.append(1.0 if weak else human_weight)
            groups.append(row.get("university") or row.get("qid") or "?")
            stats["weak" if weak else "human"] += 1
    return np.array(xs, float), np.array(ys, float), np.array(ws, float), np.array(groups), stats


# Знак вклада каждого сигнала задан смыслом, а не данными: «далеко от кампуса», «похоже на мусор»
# и «водяной знак» не могут повышать достоверность. Величину веса подбирает обучение, знак
# фиксирован. Без этого слабая разметка иногда даёт бессмысленные знаки (сервис отсекает крайние
# случаи гейтами до калибратора, и в данных остаётся мало примеров «далеко»), а карточка фото
# показывает пользователю разбор вклада сигналов - он обязан быть честным.
SIGNS = {"geo": 1, "geo_far": -1, "text": 1, "source": 1, "visual": 1, "category": 1, "trash": -1, "watermark": -1}


def fit(x: np.ndarray, y: np.ndarray, w: np.ndarray, C: float = 1.0, constrain: bool = True) -> tuple[np.ndarray, float]:
    """Логистическая регрессия с L2 и проекцией весов на допустимые знаки (проекционный градиентный спуск).

    Без ограничений (constrain=False) это обычная логистическая регрессия, её результат есть в отчёте
    для сравнения. Балансировки классов нет: слабая разметка собрана примерно поровну, а взвешивание
    классов портит калибровку вероятностей.
    """
    if not constrain:
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(C=C, max_iter=2000)
        clf.fit(x, y, sample_weight=w / w.mean())
        return clf.coef_[0], float(clf.intercept_[0])

    signs = np.array([SIGNS.get(f, 0) for f in FEATURES], dtype=np.float64)
    sw = w / w.mean()
    n = len(y)
    beta = np.zeros(x.shape[1])
    bias = 0.0
    lr = 1.0
    for step in range(6000):
        z = x @ beta + bias
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        err = sw * (p - y)
        grad = x.T @ err / n + beta / (C * n)
        beta -= lr * grad
        bias -= lr * float(err.mean())
        beta = np.where(signs > 0, np.maximum(beta, 0.0), np.where(signs < 0, np.minimum(beta, 0.0), beta))
        if step == 3000:
            lr *= 0.3
    return beta, float(bias)


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.any():
            total += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(total)


def group_folds(groups: np.ndarray, k: int, seed: int = 7) -> list[np.ndarray]:
    uniq = np.array(sorted(set(groups.tolist())))
    rng = np.random.default_rng(seed)
    rng.shuffle(uniq)
    parts = np.array_split(uniq, min(k, len(uniq)))
    return [np.where(np.isin(groups, part))[0] for part in parts]


def pick_threshold(p: np.ndarray, y: np.ndarray, target: float) -> float:
    for t in np.arange(0.6, 0.951, 0.01):
        m = p >= t
        if m.sum() >= 10 and y[m].mean() >= target:
            return round(float(t), 2)
    return 0.9


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--human-weight", type=float, default=3.0)
    ap.add_argument("--target-precision", type=float, default=0.92)
    ap.add_argument("--free-signs", action="store_true", help="без ограничения знаков (для сравнения)")
    args = ap.parse_args()
    constrain = not args.free_signs
    x, y, w, groups, stats = load(args.paths, args.human_weight)
    if len(y) < 40:
        sys.exit(f"Мало размеченных строк: {len(y)}. Нужно хотя бы 40, лучше 300+.")
    probs = np.zeros(len(y))
    for test in group_folds(groups, 5):
        train = np.setdiff1d(np.arange(len(y)), test)
        coef, b = fit(x[train], y[train], w[train], constrain=constrain)
        probs[test] = 1 / (1 + np.exp(-(x[test] @ coef + b)))
    high_t = pick_threshold(probs, y, args.target_precision)
    medium_t = round(min(0.5, high_t - 0.15), 2)
    high = probs >= high_t
    medium = (probs >= medium_t) & ~high
    metrics = {
        "cv": "5 фолдов по вузам",
        "cv_accuracy": round(float(((probs >= 0.5) == y).mean()), 3),
        "cv_brier": round(float(((probs - y) ** 2).mean()), 3),
        "cv_ece": round(ece(probs, y), 3),
        "cv_precision_high": round(float(y[high].mean()), 3) if high.any() else None,
        "cv_share_high": round(float(high.mean()), 3),
        "cv_precision_medium": round(float(y[medium].mean()), 3) if medium.any() else None,
        "cv_recall_high": round(float((high & (y == 1)).sum() / max((y == 1).sum(), 1)), 3),
        "positives": int(y.sum()), "negatives": int(len(y) - y.sum()), "universities": int(len(set(groups.tolist()))),
    }
    # Для отчёта считаем и вариант без ограничения знаков: видно, что фиксация знаков
    # почти не стоит качества, зато разбор сигналов в карточке остаётся осмысленным.
    free_probs = np.zeros(len(y))
    for test in group_folds(groups, 5):
        train = np.setdiff1d(np.arange(len(y)), test)
        fc, fb = fit(x[train], y[train], w[train], constrain=False)
        free_probs[test] = 1 / (1 + np.exp(-(x[test] @ fc + fb)))
    metrics["sign_constrained"] = constrain
    metrics["cv_accuracy_free_signs"] = round(float(((free_probs >= 0.5) == y).mean()), 3)
    metrics["cv_brier_free_signs"] = round(float(((free_probs - y) ** 2).mean()), 3)

    coef, b = fit(x, y, w, constrain=constrain)
    current = json.loads(OUT.read_text(encoding="utf-8"))
    kinds = ", ".join(f"{k}: {v}" for k, v in stats.items())
    current.update({
        "trained": True,
        "note": f"Обучено на {len(y)} примерах ({kinds}) по {metrics['universities']} вузам, кросс-валидация по вузам. "
                "Слабая разметка: категории Wikimedia Commons, см. ml/build_calibrator_data.py. "
                + ("Знак вклада каждого сигнала зафиксирован по смыслу, величина подобрана обучением." if constrain else "Знаки весов не ограничены."),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "samples": int(len(y)),
        "metrics": metrics,
        "bias": round(float(b), 4),
        "weights": {k: round(float(v), 4) for k, v in zip(FEATURES, coef)},
        "thresholds": {"high": high_t, "medium": medium_t},
    })
    OUT.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": metrics, "weights": current["weights"], "bias": current["bias"], "thresholds": current["thresholds"]}, ensure_ascii=False, indent=2))
    print(f"веса записаны в {OUT}")


if __name__ == "__main__":
    main()
