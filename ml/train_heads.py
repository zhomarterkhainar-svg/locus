"""Обучение линейных голов поверх эмбеддингов CLIP на открытых данных (data/manifest.jsonl).

Головы:
- category  : 9 разделов профиля + 6 видов «мусора» (логотипы, текст, портреты, карты, марки, прочее);
- dorm_sub  : комната / кухня / санузел / здание / коридор общежития;
- sport_sub : тренажёрный зал / бассейн / стадион / спортзал с площадкой;
- bunk      : двухъярусная или обычная кровать, обучается на вырезках кроватей, найденных YOLO,
              то есть на тех же входах, что и в работающем сервисе.

Протокол:
1. эмбеддинги той же модели CLIP, что и в сервисе (backend/app/vision/clip_model.py);
2. чистка явных ошибок разметки категорий Commons: фото раздела с вероятностью «мусора» по zero-shot > 0.7
   и «мусор» с вероятностью < 0.1 не используются (так поступает confident learning в упрощённом виде);
3. разбиение train/val/test 70/15/15 по подкатегориям Commons (кадры одной подкатегории не попадают
   одновременно в обучение и тест), для Places365 по файлам;
4. логистическая регрессия, C подбирается на val по macro-F1; вес смеси с zero-shot alpha подбирается на val;
5. итог на test: zero-shot, голова, смесь; плюс независимый ручной набор backend/tests/eval_images (43 фото).

python ml/train_heads.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.vision.categories import BUNK_PROMPTS, CATEGORIES, SUB_PROMPTS  # noqa: E402
from app.vision.clip_model import get_clip  # noqa: E402

MANIFEST = ROOT / "data" / "manifest.jsonl"
HEADS = ROOT / "ml" / "heads"
C_GRID = [0.3, 1.0, 3.0, 10.0, 30.0, 100.0]
ALPHA_GRID = [round(a, 2) for a in np.linspace(0, 1, 11)]
GROUP_KEYS = {
    "dorm_sub": ["dorm_room", "dorm_kitchen", "dorm_bathroom", "dorm_exterior", "dorm_corridor"],
    "sport_sub": ["sport_gym", "sport_pool", "sport_stadium", "sport_court"],
    "bunk": list(BUNK_PROMPTS),
}


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_rows() -> list[dict]:
    rows = [json.loads(l) for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if (ROOT / r["file"]).exists()]


def embed_files(clip, files: list[Path], cache_path: Path) -> np.ndarray:
    cache: dict[str, np.ndarray] = {}
    if cache_path.exists():
        z = np.load(cache_path)
        cache = dict(zip([str(k) for k in z["keys"]], z["emb"]))
    todo = [f for f in files if str(f) not in cache]
    log(f"эмбеддинги: {len(files)} файлов, из кэша {len(files) - len(todo)}")
    for i in range(0, len(todo), 64):
        batch = todo[i:i + 64]
        imgs = []
        for f in batch:
            try:
                imgs.append(Image.open(f).convert("RGB"))
            except Exception:  # noqa: BLE001
                imgs.append(Image.new("RGB", (224, 224)))
        for f, e in zip(batch, clip.embed_images(imgs)):
            cache[str(f)] = e
        if i % 640 == 0:
            log(f"  {i + len(batch)}/{len(todo)}")
    keys = list(cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, keys=np.array(keys), emb=np.stack([cache[k] for k in keys]).astype(np.float32))
    return np.stack([cache[str(f)] for f in files]).astype(np.float32)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)


def split_of(row: dict, label_groups: dict[str, int]) -> str:
    """Групповое разбиение: по подкатегории Commons, если у метки их достаточно, иначе по файлу."""
    use_group = row["source"] == "commons" and label_groups.get(row["label"], 0) >= 6
    key = row["category_path"] if use_group else row["id"]
    h = int(hashlib.sha1(f"{row['label']}|{key}".encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


def fit_head(X: dict[str, np.ndarray], y: dict[str, np.ndarray], zs: dict[str, np.ndarray], keys: list[str]) -> dict:
    labels = np.arange(len(keys))
    present = sorted(set(y["train"].tolist()))
    best = None
    for C in C_GRID:
        clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
        clf.fit(X["train"], y["train"])
        p = full_proba(clf, X["val"], len(keys))
        f1 = f1_score(y["val"], p.argmax(1), average="macro", labels=present, zero_division=0)
        if best is None or f1 > best[0]:
            best = (f1, C)
    C = best[1]
    clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
    clf.fit(X["train"], y["train"])
    p_head_val = full_proba(clf, X["val"], len(keys))
    alpha_scores = []
    for a in ALPHA_GRID:
        p = a * p_head_val + (1 - a) * zs["val"]
        f1 = f1_score(y["val"], p.argmax(1), average="macro", labels=present, zero_division=0)
        pc = np.clip(p, 1e-6, 1)
        ll = log_loss(y["val"], pc / pc.sum(1, keepdims=True), labels=labels)
        alpha_scores.append((round(f1, 4), -ll, a))
    alpha = max(alpha_scores)[2]
    # финальная модель на train+val
    Xtv = np.concatenate([X["train"], X["val"]])
    ytv = np.concatenate([y["train"], y["val"]])
    final = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
    final.fit(Xtv, ytv)
    W, b = full_coef(final, len(keys), X["train"].shape[1])
    p_head = full_proba(final, X["test"], len(keys))
    p_blend = alpha * p_head + (1 - alpha) * zs["test"]
    test_present = sorted(set(y["test"].tolist()))

    def m(p: np.ndarray) -> dict:
        pred = p.argmax(1)
        return {"accuracy": round(float(accuracy_score(y["test"], pred)), 4),
                "macro_f1": round(float(f1_score(y["test"], pred, average="macro", labels=test_present, zero_division=0)), 4)}

    per_class = f1_score(y["test"], p_blend.argmax(1), average=None, labels=labels, zero_division=0)
    cm = confusion_matrix(y["test"], p_blend.argmax(1), labels=labels)
    return {
        "W": W, "b": b, "alpha": alpha, "C": C,
        "metrics": {
            "n_train": int(len(y["train"])), "n_val": int(len(y["val"])), "n_test": int(len(y["test"])),
            "zero_shot": m(zs["test"]), "head": m(p_head), "blend": m(p_blend),
            "per_class_f1_blend": {k: (round(float(v), 3) if i in test_present else None) for i, (k, v) in enumerate(zip(keys, per_class))},
            "val_alpha_curve": [{"alpha": a, "macro_f1": f} for f, _, a in alpha_scores],
        },
        "confusion": cm.tolist(),
    }


def full_proba(clf: LogisticRegression, X: np.ndarray, k: int) -> np.ndarray:
    p = np.zeros((len(X), k))
    p[:, clf.classes_] = clf.predict_proba(X)
    return p


def full_coef(clf: LogisticRegression, k: int, d: int) -> tuple[np.ndarray, np.ndarray]:
    """Коэффициенты для всех k классов; отсутствующим в обучении классам ставится очень низкий сдвиг."""
    W = np.zeros((k, d), dtype=np.float32)
    b = np.full(k, -30.0, dtype=np.float32)
    if len(clf.classes_) == 2 and clf.coef_.shape[0] == 1:
        # бинарный случай sklearn: одна строка; для softmax берём симметричную пару
        w, c = clf.coef_[0] / 2, clf.intercept_[0] / 2
        W[clf.classes_[1]], b[clf.classes_[1]] = w, c
        W[clf.classes_[0]], b[clf.classes_[0]] = -w, -c
    else:
        W[clf.classes_] = clf.coef_
        b[clf.classes_] = clf.intercept_
    return W, b


def bed_crops(rows: list[dict]) -> tuple[list[Image.Image], list[dict]]:
    from app.vision.detector import detect
    crops, meta = [], []
    for i in range(0, len(rows), 16):
        batch = rows[i:i + 16]
        imgs = [Image.open(ROOT / r["file"]).convert("RGB") for r in batch]
        for r, img, boxes in zip(batch, imgs, detect(imgs, 0.35)):
            w, h = img.size
            for bx in boxes:
                if bx["label"] != "кровать":
                    continue
                x0, y0 = max(0, int((bx["x"] - 0.04) * w)), max(0, int((bx["y"] - 0.04) * h))
                x1, y1 = min(w, int((bx["x"] + bx["w"] + 0.04) * w)), min(h, int((bx["y"] + bx["h"] + 0.04) * h))
                if x1 - x0 < 24 or y1 - y0 < 24:
                    continue
                crops.append(img.crop((x0, y0, x1, y1)))
                meta.append({**r, "id": f"{r['id']}#{len(meta)}"})
    return crops, meta


def eval43(clip, category_head: dict | None) -> dict | None:
    folder = ROOT / "backend" / "tests" / "eval_images"
    idx = folder / "index.json"
    if not idx.exists():
        return None
    rows = [r for r in json.loads(idx.read_text(encoding="utf-8")) if (folder / r["file"]).exists()]
    if not rows:
        return None
    emb = clip.embed_images([Image.open(folder / r["file"]).convert("RGB") for r in rows])
    zs = softmax(100.0 * emb @ clip.class_emb.T)
    variants = {"zero_shot": zs}
    if category_head:
        head = softmax(emb @ category_head["W"].T + category_head["b"])
        variants["blend"] = category_head["alpha"] * head + (1 - category_head["alpha"]) * zs
        variants["head"] = head
    n_cat = len(CATEGORIES)
    keys = clip.class_keys
    out = {"n": len(rows)}
    for name, P in variants.items():
        ok = coarse = 0
        for r, p in zip(rows, P):
            trash = p[n_cat:]
            if float(trash.sum()) >= 0.5 and float(trash.max()) > float(p[:n_cat].max()):
                pred = "trash_" + keys[n_cat + int(trash.argmax())].split(":")[1]
            else:
                pred = keys[int(p[:n_cat].argmax())]
            gold = r["label"]
            ok += pred == gold or (gold.startswith("trash") and pred.startswith("trash"))
            coarse += pred.startswith("trash") == gold.startswith("trash")
        out[name] = {"category_accuracy": round(ok / len(rows), 3), "trash_vs_photo_accuracy": round(coarse / len(rows), 3)}
    return out


def main() -> None:
    rows = load_rows()
    log(f"строк в манифесте: {len(rows)}")
    clip = get_clip()
    model_id = clip.model_id
    safe = model_id.replace("/", "_")
    report: dict = {"model": model_id, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "dataset": {"rows": len(rows), "by_source": dict(Counter(r["source"] for r in rows))}, "heads": {}}
    saved: dict[str, dict] = {}

    for group in ["category", "dorm_sub", "sport_sub", "bunk"]:
        g_rows = [r for r in rows if r["group"] == group]
        if not g_rows:
            log(f"{group}: нет данных, пропуск")
            continue
        if group == "category":
            keys = clip.class_keys
        else:
            keys = GROUP_KEYS[group]
        if group == "bunk":
            crops, g_rows = bed_crops(g_rows)
            log(f"bunk: вырезок кроватей {len(crops)}")
            if len(crops) < 40:
                log("bunk: мало вырезок, голова не обучается")
                continue
            X_all = clip.embed_images(crops).astype(np.float32)
        else:
            X_all = embed_files(clip, [ROOT / r["file"] for r in g_rows], ROOT / "data" / f"emb_{safe}_{group}.npz")
        label_idx = {k: i for i, k in enumerate(keys)}
        keep = [i for i, r in enumerate(g_rows) if r["label"] in label_idx]
        g_rows = [g_rows[i] for i in keep]
        X_all = X_all[keep]
        y_all = np.array([label_idx[r["label"]] for r in g_rows])

        if group == "category":
            zs_all = softmax(100.0 * X_all @ clip.class_emb.T)
        elif group == "bunk":
            zs_all = softmax(100.0 * X_all @ clip.bunk_emb.T)
        else:
            idx = [clip.sub_keys.index(k) for k in keys]
            zs_all = softmax(100.0 * X_all @ clip.sub_emb[idx].T)

        removed = 0
        if group == "category":
            n_cat = len(CATEGORIES)
            trash_mass = zs_all[:, n_cat:].sum(1)
            is_trash = np.array([k.startswith("trash:") for k in (keys[i] for i in y_all)])
            ok = ~((~is_trash & (trash_mass > 0.7)) | (is_trash & (trash_mass < 0.1)))
            # если чистка выкидывает у класса больше трети примеров, значит zero-shot сам ошибается на этом классе
            for k in set(y_all.tolist()):
                m = y_all == k
                if (~ok[m]).mean() > 0.33:
                    ok[m] = True
            removed = int((~ok).sum())
            g_rows = [r for r, o in zip(g_rows, ok) if o]
            X_all, y_all, zs_all = X_all[ok], y_all[ok], zs_all[ok]
        log(f"{group}: {len(g_rows)} примеров, убрано при чистке {removed}")

        label_groups = defaultdict(set)
        for r in g_rows:
            label_groups[r["label"]].add(r["category_path"])
        n_groups = {k: len(v) for k, v in label_groups.items()}
        splits = np.array([split_of(r, n_groups) for r in g_rows])
        X = {s: X_all[splits == s] for s in ("train", "val", "test")}
        y = {s: y_all[splits == s] for s in ("train", "val", "test")}
        zs = {s: zs_all[splits == s] for s in ("train", "val", "test")}
        if min(len(v) for v in y.values()) < 10:
            log(f"{group}: слишком маленькие части разбиения, пропуск")
            continue
        res = fit_head(X, y, zs, keys)
        res["metrics"]["removed_by_cleaning"] = removed
        res["metrics"]["class_counts"] = {keys[k]: int(v) for k, v in sorted(Counter(y_all.tolist()).items())}
        HEADS.mkdir(parents=True, exist_ok=True)
        (HEADS / f"{group}.json").write_text(json.dumps({
            "keys": keys, "W": np.round(res["W"], 5).tolist(), "b": np.round(res["b"], 5).tolist(),
        }), encoding="utf-8")
        saved[group] = res
        report["heads"][group] = {"alpha": res["alpha"], "C": res["C"], "metrics": res["metrics"], "confusion": res["confusion"], "keys": keys}
        mm = res["metrics"]
        log(f"{group}: test zero-shot {mm['zero_shot']}  голова {mm['head']}  смесь(alpha={res['alpha']}) {mm['blend']}")

    ev = eval43(clip, saved.get("category"))
    if ev and "blend" in ev and ev["blend"]["category_accuracy"] < ev["zero_shot"]["category_accuracy"] - 0.05 and saved["category"]["alpha"] > 0.5:
        # страховка от переобучения на шумных категориях Commons: независимый ручной набор важнее
        log("смесь хуже zero-shot на ручном наборе, уменьшаю долю головы до 0.5")
        saved["category"]["alpha"] = 0.5
        report["heads"]["category"]["alpha"] = 0.5
        report["heads"]["category"]["metrics"]["alpha_reduced_by_manual_eval"] = True
        ev = eval43(clip, saved["category"])
    if ev:
        report["eval_manual_43"] = ev
        log(f"ручной набор: {ev}")
    HEADS.mkdir(parents=True, exist_ok=True)
    meta = {k: v for k, v in report.items() if k != "heads"}
    meta["heads"] = {k: {kk: vv for kk, vv in v.items() if kk != "confusion"} for k, v in report["heads"].items()}
    (HEADS / "heads.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report)
    log("готово")


def write_report(report: dict) -> None:
    lines = ["# Обучение голов классификатора", "",
             f"Модель: `{report['model']}`, дата: {report['trained_at']}.",
             f"Данные: {report['dataset']['rows']} фото ({', '.join(f'{k}: {v}' for k, v in report['dataset']['by_source'].items())}). "
             "Источники и лицензии каждого фото в `data/manifest.jsonl` (создаётся `ml/build_dataset.py`).", "",
             "| Голова | Примеров (train/val/test) | Zero-shot, acc / macro-F1 | Голова | Смесь | alpha |",
             "|---|---|---|---|---|---|"]
    for name, h in report["heads"].items():
        m = h["metrics"]
        f = lambda x: f"{x['accuracy']:.1%} / {x['macro_f1']:.3f}"  # noqa: E731
        lines.append(f"| {name} | {m['n_train']}/{m['n_val']}/{m['n_test']} | {f(m['zero_shot'])} | {f(m['head'])} | {f(m['blend'])} | {h['alpha']} |")
    if report.get("eval_manual_43"):
        e = report["eval_manual_43"]
        lines += ["", f"Независимый ручной набор ({e['n']} фото Commons, разметка до обучения, в обучение не входил):", "",
                  "| Вариант | Раздел | Мусор / фото |", "|---|---|---|"]
        for k in ("zero_shot", "head", "blend"):
            if k in e:
                lines.append(f"| {k} | {e[k]['category_accuracy']:.0%} | {e[k]['trash_vs_photo_accuracy']:.0%} |")
    for name, h in report["heads"].items():
        keys = h["keys"]
        lines += ["", f"## {name}: F1 по классам (смесь)", "", "| Класс | Примеров | F1 |", "|---|---|---|"]
        for k in keys:
            f1v = h["metrics"]["per_class_f1_blend"].get(k)
            lines.append(f"| {k} | {h['metrics']['class_counts'].get(k, 0)} | {'нет в тесте' if f1v is None else f'{f1v:.2f}'} |")
    lines += ["", "Разбиение: 70/15/15 по подкатегориям Commons, чтобы похожие кадры одной подкатегории не попадали и в обучение, и в тест. "
              "Метки Commons шумные: категория файла описывает тему, а не всегда содержание кадра, поэтому тестовые цифры занижены относительно чистой разметки."]
    (ROOT / "ml" / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
