"""Сборка обучающего набора фото из открытых источников.

Источники:
- Wikimedia Commons: файлы тематических категорий (dataset_spec.json), миниатюры 330 px,
  лицензии и авторы сохраняются в манифест;
- Places365-Standard, валидационная часть (CC BY, MIT CSAIL): по 100 фото нужных классов сцен.

Фото лежат только в data/images (в .gitignore) и нужны для обучения; в репозиторий попадают
только веса голов и метрики. Файлы из проверочного набора backend/tests/eval_images исключаются,
чтобы он оставался независимым тестом.

python ml/build_dataset.py              # всё
python ml/build_dataset.py --no-places  # только Commons
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commons_client import IMAGE_MIME, Commons  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "ml" / "dataset_spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "data" / "images"
MANIFEST = ROOT / "data" / "manifest.jsonl"
PLACES_BASE = "http://data.csail.mit.edu/places/places365"
GROUPS = ["category", "dorm_sub", "sport_sub", "bunk"]


def eval_titles() -> set[str]:
    p = ROOT / "backend" / "tests" / "eval_images" / "index.json"
    if not p.exists():
        return set()
    return {row["title"].removeprefix("File:").replace("_", " ") for row in json.loads(p.read_text(encoding="utf-8"))}


def save_image(data: bytes, path: Path) -> tuple[int, int] | None:
    try:
        im = Image.open(io.BytesIO(data))
        im.draft("RGB", (400, 400))
        im = im.convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    if min(im.size) < 120:
        return None
    im.thumbnail((336, 336))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=90)
    return im.size


def commons_part(c: Commons, group: str, key: str, spec: dict, limit: int, skip: set[str], banned: set[str], taken: set[str]) -> list[dict]:
    titles: dict[str, str] = {}
    per_cat = max(40, limit // max(1, len(spec["commons"])) + 30)
    for cat, depth in spec["commons"]:
        for title, path in c.files_in_tree(cat, depth, per_cat * 2, skip):
            if title.removeprefix("File:").replace("_", " ") in banned or title in taken:
                continue
            titles.setdefault(title, f"{cat}|{path}")
    items = list(titles.items())
    random.Random(f"{group}:{key}").shuffle(items)
    infos = c.imageinfo([t for t, _ in items[: limit * 2]], width=330)
    rows = []
    for title, src in items:
        page = infos.get(title)
        if not page:
            continue
        info = page["imageinfo"][0]
        if info.get("mime") not in IMAGE_MIME or not info.get("thumburl"):
            continue
        ext = info.get("extmetadata", {})
        rows.append({
            "group": group, "label": key, "source": "commons", "title": title, "source_category": src.split("|")[0],
            "category_path": src.split("|")[1], "url": info["thumburl"], "page": info.get("descriptionurl"),
            "license": ext.get("LicenseShortName", {}).get("value", ""), "author": ext.get("Artist", {}).get("value", "")[:200],
        })
        taken.add(title)
        if len(rows) >= limit:
            break
    return rows


def download_rows(c: Commons, rows: list[dict], workers: int = 6) -> list[dict]:
    def job(row: dict) -> dict | None:
        digest = hashlib.sha1(row["url"].encode()).hexdigest()[:16]
        path = OUT / row["group"] / row["label"].replace(":", "_") / f"{digest}.jpg"
        if path.exists():
            return {**row, "file": str(path.relative_to(ROOT)), "id": digest}
        data = c.download(row["url"])
        if not data:
            return None
        size = save_image(data, path)
        if not size:
            return None
        return {**row, "file": str(path.relative_to(ROOT)), "id": digest}

    with ThreadPoolExecutor(workers) as ex:
        return [r for r in ex.map(job, rows) if r]


def places_part(needed: dict[str, list[tuple[str, str]]], per_class: int) -> list[dict]:
    """needed: имя класса Places365 -> [(group, label)]. Качает val_256.tar потоком и берёт нужные файлы."""
    names = [l.split()[0][3:] for l in (ROOT / "ml" / "categories_places365.txt").read_text().splitlines() if l.strip()]
    tmp = ROOT / "data" / "places"
    tmp.mkdir(parents=True, exist_ok=True)
    flist = tmp / "filelist.tar"
    if not flist.exists():
        print("places365: скачиваю список файлов")
        urllib.request.urlretrieve(f"{PLACES_BASE}/filelist_places365-standard.tar", flist)
    with tarfile.open(flist) as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("places365_val.txt"))
        lines = tf.extractfile(member).read().decode().splitlines()
    wanted: dict[str, str] = {}
    counts: dict[str, int] = {}
    for line in lines:
        fname, idx = line.split()
        cls = names[int(idx)]
        if cls in needed and counts.get(cls, 0) < per_class:
            wanted[fname] = cls
            counts[cls] = counts.get(cls, 0) + 1
    print(f"places365: нужно {len(wanted)} фото из {len(counts)} классов, качаю val_256.tar (~500 МБ) потоком")
    rows = []
    req = urllib.request.Request(f"{PLACES_BASE}/val_256.tar", headers={"User-Agent": "CandidAI-trainer"})
    with urllib.request.urlopen(req, timeout=120) as resp, tarfile.open(fileobj=resp, mode="r|") as tf:
        for m in tf:
            base = m.name.rsplit("/", 1)[-1]
            cls = wanted.get(base)
            if not cls:
                continue
            data = tf.extractfile(m).read()
            for group, label in needed[cls]:
                path = OUT / group / label.replace(":", "_") / f"places_{base}"
                if not path.exists() and not save_image(data, path):
                    continue
                rows.append({"group": group, "label": label, "source": "places365", "title": base, "source_category": f"places365/{cls}",
                             "category_path": cls, "url": f"{PLACES_BASE}/val_256.tar#{base}", "page": "http://places2.csail.mit.edu/",
                             "license": "CC BY (Places365, MIT CSAIL)", "author": "Places365 team",
                             "file": str(path.relative_to(ROOT)), "id": f"places_{base}"})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-places", action="store_true")
    ap.add_argument("--limit", type=int, default=SPEC["per_class_limit"])
    ap.add_argument("--groups", default=",".join(GROUPS))
    args = ap.parse_args()
    random.seed(7)
    c = Commons()
    banned = eval_titles()
    skip = set(SPEC.get("skip_subcategories", []))
    rows: list[dict] = []
    needed: dict[str, list[tuple[str, str]]] = {}
    for group in args.groups.split(","):
        limit = args.limit if group == "category" else max(120, args.limit // 2)
        taken: set[str] = set()  # один файл в группе получает одну метку
        for key, spec in SPEC[group].items():
            part = commons_part(c, group, key, spec, limit, skip if not key.startswith("trash:") else set(), banned, taken)
            got = download_rows(c, part)
            print(f"commons {group}/{key}: {len(got)} фото")
            rows += got
            for p in spec.get("places365", []):
                needed.setdefault(p, []).append((group, key))
    if needed and not args.no_places:
        try:
            got = places_part(needed, SPEC.get("places_per_class", 100))
            print(f"places365: {len(got)} фото")
            rows += got
        except Exception as e:  # noqa: BLE001
            print(f"places365 недоступен ({e}), продолжаю только с Commons")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"манифест: {MANIFEST} ({len(rows)} строк)")


if __name__ == "__main__":
    main()
