"""Слабая разметка для калибратора достоверности (distant supervision по структуре Wikimedia Commons).

Идея: файл из дерева категорий вуза A (свойство P373 в Wikidata) относится к A — это положительный пример.
Файл из дерева категорий другого вуза B, оценённый как кандидат для A, — отрицательный (сложные
отрицательные: по возможности вуз из того же города или страны). Для каждой пары (файл, вуз) признаки
считаются тем же кодом, что и в сервисе: геометка относительно границы кампуса OSM, название в подписи,
способ нахождения, сходство с главным фото, уверенность классификатора, мусор, водяной знак.

Чтобы разметка не подсказывала ответ: для кандидатов, «найденных» поиском или по геометке, из подписи
убирается категория, по которой поставлена метка. Кандидаты, которые сервис отклонил бы до калибратора
(мусор, далеко от кампуса без названия), в набор не входят.

python ml/build_calibrator_data.py            # пишет data/labels/weak_commons.jsonl
"""
from __future__ import annotations

import asyncio
import io
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

from commons_client import Commons  # noqa: E402

from app import http  # noqa: E402
from app.search import wikidata  # noqa: E402
from app.sources import commons as commons_src  # noqa: E402
from app.sources import osm  # noqa: E402
from app.verify.signals import NameMatcher, build as build_signals  # noqa: E402
from app.vision.categories import CATEGORIES  # noqa: E402
from app.vision.clip_model import get_clip  # noqa: E402

UNIVERSITIES = [
    # Казахстан
    "Евразийский национальный университет", "Казахский национальный университет имени аль-Фараби", "Nazarbayev University",
    "KIMEP University", "Suleyman Demirel University", "Казахстанско-Британский технический университет", "Satbayev University",
    "Astana IT University", "Казахский национальный медицинский университет", "Карагандинский университет имени Букетова",
    "Южно-Казахстанский университет имени Ауэзова", "Торайгыров университет", "Казахский агротехнический университет",
    "Казахский национальный педагогический университет имени Абая", "Университет Туран",
    # Центральная Азия и соседи
    "American University of Central Asia", "Кыргызский национальный университет", "Национальный университет Узбекистана",
    "Белорусский государственный университет", "Киевский национальный университет имени Тараса Шевченко",
    # Россия
    "Московский государственный университет", "Санкт-Петербургский государственный университет", "Московский физико-технический институт",
    "Высшая школа экономики", "Новосибирский государственный университет", "Уральский федеральный университет",
    "Казанский федеральный университет", "Томский государственный университет",
    # Мир
    "Massachusetts Institute of Technology", "Stanford University", "Harvard University", "University of Oxford",
    "University of Cambridge", "ETH Zurich", "Technical University of Munich", "University of Tokyo", "Tsinghua University",
    "National University of Singapore", "Seoul National University", "Middle East Technical University",
    "Charles University", "University of Warsaw",
]
PRIORS = {"category": 0.8, "search": 0.55, "geo": 0.45}
OUT = ROOT / "data" / "labels" / "weak_commons.jsonl"


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


async def resolve(name: str):
    res = await wikidata.search(name)
    for cand in res["candidates"][:3]:
        uni = await wikidata.get_university(cand["qid"])
        if uni.commons_category:
            return uni
    return None


def fetch_image(c: Commons, url: str) -> Image.Image | None:
    data = c.download(url)
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None


def strip_category(context: str, category: str) -> str:
    parts = [p.strip() for p in context.removeprefix("Категории Commons:").split(";")]
    low = category.lower()
    kept = [p for p in parts if p and low not in p.lower() and p.lower() not in low]
    return "Категории Commons: " + "; ".join(kept)


async def main() -> None:
    rng = random.Random(11)
    c = Commons()
    clip = get_clip()
    unis = []
    for name in UNIVERSITIES:
        try:
            uni = await resolve(name)
        except Exception as e:  # noqa: BLE001
            log(f"не найден {name}: {e}")
            continue
        if uni and uni.qid not in {u.qid for u in unis}:
            unis.append(uni)
            log(f"{name} -> {uni.qid} {uni.label} [{uni.commons_category}]")
        await asyncio.sleep(0.5)

    # 1. файлы дерева категорий каждого вуза
    files: dict[str, list[dict]] = {}
    for uni in unis:
        titles = [t for t, _ in c.files_in_tree(uni.commons_category, 2, 70, {"logo", "map", "people", "portrait", "svg"})]
        infos = c.imageinfo(titles, width=330)
        lead = f"File:{uni.image}" if uni.image else None
        files[uni.qid] = [p for t, p in infos.items() if t != lead and p["imageinfo"][0].get("mime") in commons_src.IMAGE_MIME]
        log(f"{uni.label}: {len(files[uni.qid])} файлов")

    # 2. изображения и эмбеддинги (каждый файл один раз)
    all_pages = {p["title"]: p for ps in files.values() for p in ps}
    urls = {t: p["imageinfo"][0].get("thumburl") for t, p in all_pages.items()}
    with ThreadPoolExecutor(6) as ex:
        images = dict(zip(urls, ex.map(lambda u: fetch_image(c, u) if u else None, urls.values())))
    titles = [t for t, im in images.items() if im is not None]
    log(f"скачано {len(titles)} из {len(urls)}")
    emb = np.concatenate([clip.embed_images([images[t] for t in titles[i:i + 64]]) for i in range(0, len(titles), 64)])
    emb_of = dict(zip(titles, emb))
    probs = clip.classify(emb)
    wm = clip.watermark(emb)
    n_cat = len(CATEGORIES)
    feats_of = {}
    for t, p, w in zip(titles, probs, wm):
        cat = p[:n_cat]
        feats_of[t] = {"category_p": float(cat.max() / max(cat.sum(), 1e-6)), "trash_p": float(p[n_cat:].sum()),
                       "trash_gate": float(p[n_cat:].sum()) >= 0.5 and float(p[n_cat:].max()) > float(cat.max()),
                       "watermark": float(w)}

    # 3. пары (файл, вуз)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n_pos = n_neg = dropped = 0
    with OUT.open("w", encoding="utf-8") as f:
        for uni in unis:
            campus = osm.Campus(center=(uni.lat, uni.lon)) if uni.lat is not None else osm.Campus()
            if uni.lat is not None:
                try:
                    campus = await osm.fetch_campus(uni, wait_s=60)
                except Exception as e:  # noqa: BLE001
                    log(f"OSM для {uni.label}: {e}")
            matcher = NameMatcher.for_university(uni)
            ref = None
            if uni.image:
                lead = c.imageinfo([f"File:{uni.image}"], width=330)
                page = next(iter(lead.values()), None)
                im = fetch_image(c, page["imageinfo"][0]["thumburl"]) if page else None
                if im is not None:
                    ref = clip.embed_images([im])[0]
            same_city = [u for u in unis if u.qid != uni.qid and u.city and uni.city and u.city.qid == uni.city.qid]
            same_country = [u for u in unis if u.qid != uni.qid and u.country and uni.country and u.country.qid == uni.country.qid and u not in same_city]
            others = [u for u in unis if u.qid != uni.qid and u not in same_city and u not in same_country]
            neg_pool: list[tuple[dict, str]] = []
            for group, share in ((same_city, 25), (same_country, 15), (others, 20)):
                pool = [(p, u.commons_category) for u in group for p in files.get(u.qid, [])]
                rng.shuffle(pool)
                neg_pool += pool[:share]
            pos_pool = [(p, uni.commons_category) for p in files.get(uni.qid, [])]
            for label, pool in ((1, pos_pool), (0, neg_pool)):
                for page, defining in pool:
                    t = page["title"]
                    if t not in feats_of:
                        continue
                    ft = feats_of[t]
                    if ft["trash_gate"]:
                        dropped += 1
                        continue
                    origin = rng.choices(["category", "search", "geo"], [0.5, 0.25, 0.25])[0] if label else rng.choices(["search", "geo"], [0.4, 0.6])[0]
                    cand = commons_src._candidate(page, origin, PRIORS[origin], "campus")
                    if cand is None:
                        continue
                    if origin != "category":
                        cand.context = strip_category(cand.context, defining)
                    ref_sim = float(ref @ emb_of[t]) if ref is not None else None
                    conf, signals, dist, _, text_score = build_signals(cand, uni, campus, matcher, ft["category_p"], ft["trash_p"], ft["watermark"], ref_sim)
                    geo = next(s for s in signals if s.key == "geo")
                    if geo.value < 0 and text_score == 0:
                        dropped += 1  # сервис отклоняет такие фото как «далеко от кампуса» до калибратора
                        continue
                    row = {"id": cand.id, "university": uni.qid, "title": t, "origin": origin, "label": label, "weak": True,
                           "source_university_category": defining, "features": {s.key: s.value for s in signals},
                           "distance_m": None if dist is None else round(dist), "confidence_before": round(conf, 4)}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n_pos += label
                    n_neg += 1 - label
            log(f"{uni.label}: итого положительных {n_pos}, отрицательных {n_neg}")
    log(f"готово: {OUT} (+{n_pos} / -{n_neg}, отброшено гейтами сервиса {dropped})")
    await http.close()


if __name__ == "__main__":
    asyncio.run(main())
