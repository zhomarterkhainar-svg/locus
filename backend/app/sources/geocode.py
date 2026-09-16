"""Запасные координаты вуза, если в Wikidata нет P625 (например, у КазНУ им. аль-Фараби).

OpenStreetMap Nominatim: ищем объект-вуз по названию; надёжнее всего совпадение тега wikidata,
иначе объект amenity=university/college не дальше 60 км от города вуза. Правила Nominatim:
не чаще 1 запроса в секунду, User-Agent с контактом, результаты кэшируются.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .. import cache
from ..domain import University
from ..geo import haversine
from ..http import SourceError, get_json

API = "https://nominatim.openstreetmap.org/search"
_lock = asyncio.Lock()
EDU_TYPES = {"university", "college", "school"}


def pick(results: list[dict[str, Any]], uni: University) -> tuple[float, float, str] | None:
    for r in results:
        if (r.get("extratags") or {}).get("wikidata") == uni.qid:
            return float(r["lat"]), float(r["lon"]), "тег wikidata в OpenStreetMap"
    for r in results:
        if r.get("category") != "amenity" or r.get("type") not in EDU_TYPES:
            continue
        lat, lon = float(r["lat"]), float(r["lon"])
        if uni.city and uni.city.lat is not None and haversine((lat, lon), (uni.city.lat, uni.city.lon)) > 60_000:
            continue
        return lat, lon, "поиск по названию в OpenStreetMap"
    return None


async def locate(uni: University, budget_s: float = 5.0) -> tuple[float, float, str] | None:
    hit = cache.get("geocode", uni.qid, 30 * 24 * 3600)
    if hit is not None:
        return tuple(hit[0]) if hit[0] else None  # type: ignore[return-value]
    queries = []
    for name in (uni.labels.get("en"), uni.labels.get("ru"), uni.label):
        if name and name not in queries:
            queries.append(name)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    found = None
    async with _lock:
        for i, q in enumerate(queries[:3]):
            remaining = deadline - loop.time()
            if remaining <= 0.5:
                break
            if i:
                await asyncio.sleep(1.05)
            try:
                results = await get_json(API, {"q": q, "format": "jsonv2", "limit": 5, "extratags": 1}, timeout=min(4.0, remaining))
            except SourceError:
                continue
            found = pick(results if isinstance(results, list) else [], uni)
            if found:
                break
    cache.put("geocode", uni.qid, list(found) if found else None)
    return found
