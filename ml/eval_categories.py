"""Проверка zero-shot категорий на небольшом размеченном наборе фото Commons.

Это санитарная проверка промптов, а не бенчмарк качества: набор маленький (десятки фото),
метки ставились вручную по содержанию кадра.

python ml/eval_categories.py backend/tests/eval_images
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image  # noqa: E402

from app.vision.categories import CATEGORIES  # noqa: E402
from app.vision.clip_model import get_clip  # noqa: E402


def predict_label(keys, probs, sims, n_cat):
    cat_idx = int(probs[:n_cat].argmax())
    trash = probs[n_cat:]
    if float(trash.sum()) >= 0.5 and float(trash.max()) > float(probs[:n_cat].max()):
        return "trash_" + keys[n_cat + int(trash.argmax())].split(":")[1]
    return keys[cat_idx]


def main(folder: str) -> None:
    folder_p = Path(folder)
    rows = json.loads((folder_p / "index.json").read_text(encoding="utf-8"))
    clip = get_clip()
    images = [Image.open(folder_p / r["file"]).convert("RGB") for r in rows]
    emb = clip.embed_images(images)
    probs = clip.classify(emb)
    sims = emb @ clip.class_emb.T
    n_cat = len(CATEGORIES)
    correct = 0
    coarse = 0
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r, p, s in zip(rows, probs, sims):
        pred = predict_label(clip.class_keys, p, s, n_cat)
        gold = r["label"]
        is_trash_gold = gold.startswith("trash")
        ok = pred == gold or (is_trash_gold and pred.startswith("trash"))
        correct += ok
        coarse += (pred.startswith("trash") == is_trash_gold)
        confusion[gold][pred] += 1
        mark = "ok " if ok else "ERR"
        print(f"{mark} {gold:15s} -> {pred:15s} max_sim={float(s.max()):.3f}  {r['title'][:50]}")
    n = len(rows)
    print(f"\nкатегория (мусор любого вида считается одной меткой): {correct}/{n} = {correct / n:.0%}")
    print(f"мусор / не мусор: {coarse}/{n} = {coarse / n:.0%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "backend/tests/eval_images"))
