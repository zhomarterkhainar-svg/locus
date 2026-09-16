"""OpenStreetMap через Overpass: граница кампуса и объекты рядом."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import cache
from ..config import get_settings
from ..domain import University
from ..geo import Point, bbox_diag, centroid, distance_to_rings, haversine, stitch_ways
from ..http import SourceError, client

KIND_LABELS = {
    "dormitory": "Общежитие",
    "academic": "Учебный корпус",
    "library": "Библиотека",
    "sport": "Спорт",
    "canteen": "Столовая",
    "other_university": "Другой вуз",
    "transport": "Остановка транспорта",
    "shop": "Магазин",
    "pharmacy": "Аптека",
}
# Объекты повседневной инфраструктуры: не часть кампуса, считаются в радиусе от него
AMENITY_KINDS = {"transport", "shop", "pharmacy"}
log = logging.getLogger("candid.osm")


@dataclass
class OsmObject:
    osm: str
    kind: str
    sport: str | None
    name: str
    lat: float
    lon: float

    def public(self) -> dict[str, Any]:
        return {"osm": self.osm, "kind": self.kind, "kind_label": KIND_LABELS.get(self.kind, self.kind),
                "sport": self.sport, "name": self.name, "lat": self.lat, "lon": self.lon,
                "url": f"https://www.openstreetmap.org/{self.osm}"}


@dataclass
class Campus:
    rings: list[list[Point]] = field(default_factory=list)
    center: Point | None = None
    radius_m: float = 700.0
    objects: list[OsmObject] = field(default_factory=list)
    matched_by: str = "coordinates"  # wikidata-tag | coordinates
    from_cache: bool = False
    cache_age_s: float | None = None

    def distance(self, p: Point) -> float:
        if self.rings:
            return distance_to_rings(p, self.rings)
        if self.center:
            return max(0.0, haversine(p, self.center) - self.radius_m * 0.5)
        return float("inf")

    def nearest(self, p: Point, kinds: set[str] | None = None) -> tuple[OsmObject, float] | None:
        best = None
        for o in self.objects:
            if kinds and o.kind not in kinds:
                continue
            d = haversine(p, (o.lat, o.lon))
            if best is None or d < best[1]:
                best = (o, d)
        return best

    def public(self) -> dict[str, Any]:
        return {
            "rings": [[[round(lat, 6), round(lon, 6)] for lat, lon in r] for r in self.rings],
            "center": list(self.center) if self.center else None,
            "radius_m": round(self.radius_m),
            "matched_by": self.matched_by,
            "from_cache": self.from_cache,
            "objects": [o.public() for o in self.objects if o.kind not in AMENITY_KINDS],
            "amenities": [o.public() for o in self.objects if o.kind in AMENITY_KINDS],
        }


def _kind(tags: dict[str, str], own_qid: str) -> tuple[str, str | None] | None:
    leisure = tags.get("leisure", "")
    if tags.get("highway") == "bus_stop" or tags.get("public_transport") in {"platform", "stop_position"} or tags.get("railway") in {"tram_stop", "station", "subway_entrance"}:
        return "transport", tags.get("railway") or "bus"
    if tags.get("shop") in {"supermarket", "convenience", "mall"}:
        return "shop", tags.get("shop")
    if tags.get("amenity") == "pharmacy":
        return "pharmacy", None
    if tags.get("building") == "dormitory" or tags.get("amenity") == "dormitory":
        return "dormitory", None
    if leisure in {"sports_centre", "stadium", "pitch", "swimming_pool", "fitness_centre", "sports_hall", "track"}:
        return "sport", tags.get("sport") or leisure
    if tags.get("amenity") == "library":
        return "library", None
    if tags.get("amenity") in {"canteen"}:
        return "canteen", None
    if tags.get("amenity") in {"university", "college"} or tags.get("building") == "university":
        if tags.get("wikidata") and tags["wikidata"] != own_qid and tags.get("amenity") in {"university", "college"}:
            return "other_university", None
        return "academic", None
    return None


def build_query(uni: University, lat: float, lon: float, radius: int) -> str:
    near = min(radius, 900)
    return f"""[out:json][timeout:25];
nwr(around:3000,{lat},{lon})["wikidata"="{uni.qid}"]->.own;
.own out geom;
(
  nwr(around:{radius},{lat},{lon})["amenity"~"^(university|college|library|canteen|dormitory)$"];
  nwr(around:{radius},{lat},{lon})["building"~"^(dormitory|university)$"];
  nwr(around:{radius},{lat},{lon})["leisure"~"^(sports_centre|stadium|pitch|swimming_pool|fitness_centre|sports_hall)$"];
);
out tags center 250;
(
  node(around:{near},{lat},{lon})["highway"="bus_stop"];
  node(around:{near},{lat},{lon})["railway"~"^(tram_stop|station|subway_entrance)$"];
  nwr(around:{near},{lat},{lon})["shop"~"^(supermarket|convenience|mall)$"];
  nwr(around:{near},{lat},{lon})["amenity"="pharmacy"];
);
out tags center 120;"""


def parse(data: dict[str, Any], uni: University) -> Campus:
    campus = Campus()
    own_ways: list[list[Point]] = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("wikidata") == uni.qid and ("members" in el or "geometry" in el):
            if el["type"] == "relation":
                for m in el.get("members", []):
                    if m.get("role") in ("outer", "") and m.get("geometry"):
                        own_ways.append([(g["lat"], g["lon"]) for g in m["geometry"]])
            elif el["type"] == "way" and el.get("geometry"):
                own_ways.append([(g["lat"], g["lon"]) for g in el["geometry"]])
            continue
        if tags.get("wikidata") == uni.qid:
            if el["type"] == "node":
                campus.center = (el["lat"], el["lon"])
                campus.matched_by = "wikidata-tag"
            continue
        kind = _kind(tags, uni.qid)
        if not kind:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        name = tags.get("name:ru") or tags.get("name") or tags.get("name:kk") or tags.get("name:en") or ""
        obj = OsmObject(osm=f"{el['type']}/{el['id']}", kind=kind[0], sport=kind[1], name=name, lat=lat, lon=lon)
        obj._is_edu_amenity = tags.get("amenity") in {"university", "college"}  # type: ignore[attr-defined]
        campus.objects.append(obj)
    if own_ways:
        campus.rings = stitch_ways(own_ways)
        campus.center = centroid(campus.rings)
        campus.radius_m = max(250.0, bbox_diag(campus.rings) / 2)
        campus.matched_by = "wikidata-tag"
    if campus.center is None and uni.lat is not None:
        campus.center = (uni.lat, uni.lon)
    if campus.rings:
        for o in campus.objects:
            if getattr(o, "_is_edu_amenity", False) and o.kind == "academic" and campus.distance((o.lat, o.lon)) > 40:
                o.kind = "other_university"
        # Объекты «своего» вуза оставляем только в пределах разумного отступа от границы
        campus.objects = [o for o in campus.objects
                          if o.kind == "other_university" or o.kind in AMENITY_KINDS or campus.distance((o.lat, o.lon)) <= 400]
    # Дубли одного объекта (узел и контур с одним именем) не нужны
    seen: set[tuple[str, str, int, int]] = set()
    uniq = []
    for o in campus.objects:
        k = (o.kind, o.name, round(o.lat * 2000), round(o.lon * 2000))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(o)
    campus.objects = uniq
    return campus


_inflight: dict[str, asyncio.Task] = {}


async def _race_mirrors(q: str, per_request_timeout: float) -> dict[str, Any]:
    """Опрашивает зеркала Overpass параллельно и берёт первый корректный ответ."""
    s = get_settings()
    c = await client()
    errors: list[str] = []

    async def one(url: str) -> dict[str, Any]:
        try:
            r = await c.post(url, data={"data": q}, timeout=per_request_timeout)
        except httpx.HTTPError as e:
            raise SourceError(type(e).__name__) from e
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code}")
        try:
            data = json.loads(r.text)
        except ValueError as e:
            raise SourceError("перегружен (ответ не JSON)") from e
        if "remark" in data and not data.get("elements") and "runtime error" in str(data.get("remark", "")):
            raise SourceError("перегружен (runtime error)")
        return data

    tasks = [asyncio.create_task(one(u)) for u in s.overpass_urls]
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                return await fut
            except SourceError as e:
                errors.append(str(e))
    finally:
        for t in tasks:
            t.cancel()
    raise SourceError(f"Overpass: {errors[0] if errors else 'нет ответа'}")


KEEP_TAGS = {"amenity", "building", "leisure", "sport", "highway", "railway", "public_transport", "shop", "wikidata",
             "name", "name:ru", "name:kk", "name:en"}


def compact(data: dict[str, Any]) -> dict[str, Any]:
    """Оставляет в ответе Overpass только то, что читает parse(): кэш меньше в разы."""
    out = []
    for el in data.get("elements", []):
        e: dict[str, Any] = {"type": el.get("type"), "id": el.get("id")}
        for k in ("lat", "lon", "center"):
            if k in el:
                e[k] = el[k]
        tags = {k: v for k, v in el.get("tags", {}).items() if k in KEEP_TAGS}
        if tags:
            e["tags"] = tags
        if "geometry" in el:
            e["geometry"] = [{"lat": round(g["lat"], 6), "lon": round(g["lon"], 6)} for g in el["geometry"] if g]
        if "members" in el:
            e["members"] = [{"role": m.get("role", ""), "geometry": [{"lat": round(g["lat"], 6), "lon": round(g["lon"], 6)} for g in m["geometry"] if g]}
                            for m in el["members"] if m.get("geometry")]
        out.append(e)
    return {"elements": out}


async def _load_raw(uni: University) -> dict[str, Any]:
    s = get_settings()
    q = build_query(uni, uni.lat, uni.lon, 1400)
    data = compact(await _race_mirrors(q, s.osm_background_timeout))
    cache.put("osm", uni.qid, data)
    return data


def _from_raw(data: dict[str, Any], uni: University, age: float | None) -> Campus:
    campus = parse(data, uni)
    campus.from_cache = age is not None
    campus.cache_age_s = age
    return campus


def cached_campus(uni: University) -> Campus | None:
    hit = cache.get("osm", uni.qid, get_settings().osm_cache_ttl_s, seed=True)
    if hit is None:
        return None
    return _from_raw(hit[0], uni, hit[1])


def background_task(uni: University) -> asyncio.Task:
    """Одна загрузка на вуз: если сборка не дождалась Overpass, загрузка продолжается и заполняет кэш."""
    task = _inflight.get(uni.qid)
    if task is None or task.done():
        task = asyncio.create_task(_load_raw(uni))
        _inflight[uni.qid] = task

        def _done(t: asyncio.Task, qid: str = uni.qid) -> None:
            if _inflight.get(qid) is t:
                _inflight.pop(qid, None)
            if not t.cancelled() and t.exception() is not None:
                log.info("overpass background for %s failed: %s", qid, t.exception())

        task.add_done_callback(_done)
    return task


async def fetch_campus(uni: University, wait_s: float | None = None) -> Campus:
    if uni.lat is None:
        return Campus()
    hit = cached_campus(uni)
    if hit is not None:
        return hit
    task = background_task(uni)
    timeout = get_settings().osm_timeout if wait_s is None else wait_s
    try:
        data = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise SourceError(f"Overpass не ответил за {timeout:.0f} с, карта догружается в фоне") from e
    return _from_raw(data, uni, None)
