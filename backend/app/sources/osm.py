"""OpenStreetMap через Overpass: граница кампуса и объекты рядом."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

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
}


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
            "objects": [o.public() for o in self.objects],
        }


def _kind(tags: dict[str, str], own_qid: str) -> tuple[str, str | None] | None:
    leisure = tags.get("leisure", "")
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
    return f"""[out:json][timeout:8];
nwr(around:3000,{lat},{lon})["wikidata"="{uni.qid}"]->.own;
.own out geom;
(
  nwr(around:{radius},{lat},{lon})["amenity"~"^(university|college|library|canteen|dormitory)$"];
  nwr(around:{radius},{lat},{lon})["building"~"^(dormitory|university)$"];
  nwr(around:{radius},{lat},{lon})["leisure"~"^(sports_centre|stadium|pitch|swimming_pool|fitness_centre|sports_hall)$"];
);
out tags center 250;"""


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
        campus.objects = [o for o in campus.objects if o.kind == "other_university" or campus.distance((o.lat, o.lon)) <= 400]
    return campus


async def fetch_campus(uni: University) -> Campus:
    if uni.lat is None:
        return Campus()
    s = get_settings()
    q = build_query(uni, uni.lat, uni.lon, 1400)
    c = await client()
    last = "нет ответа"
    for url in s.overpass_urls:
        try:
            r = await c.post(url, data={"data": q}, timeout=s.osm_timeout / len(s.overpass_urls) + 2)
        except httpx.HTTPError as e:
            last = type(e).__name__
            continue
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            continue
        try:
            return parse(json.loads(r.text), uni)
        except ValueError:
            last = "перегружен (ответ не JSON)"
            continue
    raise SourceError(f"Overpass: {last}")
