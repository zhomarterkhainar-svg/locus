"""Факты из фото: что видно на снимках общежитий и спортивных объектов.

Правила честности:
- одно доказательство = один кластер дубликатов (копии не считаются повторно);
- меньше двух независимых фото = статус «мало данных», значение показывается как наблюдение;
- «не найдено» не означает «нет»: сервис говорит только о том, что видно.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from ..domain import Photo
from ..sources.osm import Campus


@dataclass
class Fact:
    id: str
    group: str
    label: str
    value: str
    status: str  # confirmed | weak | insufficient | not_found
    note: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    osm: list[dict[str, Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return self.__dict__


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def _independent(photos: list[Photo]) -> list[Photo]:
    seen: set[str] = set()
    out = []
    for p in sorted(photos, key=lambda p: p.confidence, reverse=True):
        if p.cluster in seen:
            continue
        seen.add(p.cluster)
        out.append(p)
    return out


MIN_CONF = {"кровать": 0.45, "стол": 0.35, "стул": 0.35}


def _evidence(p: Photo, labels: set[str] | None = None) -> dict[str, Any]:
    boxes = [b for b in p.boxes if (labels is None or b["label"] in labels) and b["conf"] >= MIN_CONF.get(b["label"], 0.3)]
    return {"photo_id": p.candidate.id, "shelfmark": p.shelfmark, "boxes": boxes}


def _count(p: Photo, label: str, min_conf: float | None = None) -> int:
    threshold = MIN_CONF.get(label, 0.3) if min_conf is None else min_conf
    return sum(1 for b in p.boxes if b["label"] == label and b["conf"] >= threshold)


def _status(n: int, strong: int = 3) -> str:
    if n >= strong:
        return "confirmed"
    if n >= 2:
        return "weak"
    if n == 1:
        return "insufficient"
    return "not_found"


def dorm_facts(photos: list[Photo], campus: Campus) -> list[Fact]:
    dorm = _independent([p for p in photos if p.category == "dormitory" and p.level != "low"])
    rooms = [p for p in dorm if _count(p, "кровать") > 0 or p.sub.get("dorm_room", 0) > 0.5]
    facts: list[Fact] = []

    with_beds = [p for p in rooms if _count(p, "кровать") > 0]
    if with_beds:
        counts = [_count(p, "кровать") for p in with_beds]
        lo, hi = min(counts), max(counts)
        med = statistics.median(counts)
        value = f"{lo}" if lo == hi else f"{lo}–{hi}, чаще {med:g}"
        n = len(with_beds)
        facts.append(Fact(
            id="dorm_beds", group="dormitory", label="Кроватей на фото комнаты", value=value,
            status=_status(n), evidence=[_evidence(p, {"кровать"}) for p in with_beds],
            note=f"Подсчитано детектором на {n} {_plural(n, 'независимом фото', 'независимых фото', 'независимых фото')}. "
                 "В кадр может попасть не вся комната; двухъярусная кровать может считаться как одна.",
        ))
    else:
        facts.append(Fact(id="dorm_beds", group="dormitory", label="Кроватей на фото комнаты", value="мало данных",
                          status="not_found", note="Подтверждённых фото жилых комнат не найдено."))

    desks = [p for p in rooms if _count(p, "стол", 0.35) > 0]
    if rooms:
        facts.append(Fact(
            id="dorm_desks", group="dormitory", label="Столы в комнатах",
            value=f"видны на {len(desks)} из {len(rooms)} фото" if desks else "на фото не видны",
            status=_status(len(desks)) if desks else "insufficient",
            evidence=[_evidence(p, {"стол", "стул"}) for p in desks],
            note="Детектор распознаёт столы и стулья, но не их владельца, поэтому «стол на каждого» не утверждается.",
        ))

    kitchen = [p for p in dorm if p.sub.get("dorm_kitchen", 0) > 0.55 or any(_count(p, l) for l in ("холодильник", "микроволновка", "плита"))]
    facts.append(Fact(
        id="dorm_kitchen", group="dormitory", label="Фото кухни",
        value=f"есть, {len(kitchen)}" if kitchen else "не найдено",
        status=_status(len(kitchen), strong=2) if kitchen else "not_found",
        evidence=[_evidence(p, {"холодильник", "микроволновка", "плита", "раковина"}) for p in kitchen],
        note="Кухня засчитывается по технике в кадре или по классификатору помещения. «Не найдено» не значит, что кухни нет.",
    ))
    bath = [p for p in dorm if p.sub.get("dorm_bathroom", 0) > 0.55 or _count(p, "унитаз")]
    facts.append(Fact(
        id="dorm_bathroom", group="dormitory", label="Фото душевой или санузла",
        value=f"есть, {len(bath)}" if bath else "не найдено",
        status=_status(len(bath), strong=2) if bath else "not_found",
        evidence=[_evidence(p, {"унитаз", "раковина"}) for p in bath],
    ))
    dorm_osm = [o for o in campus.objects if o.kind == "dormitory"]
    if dorm_osm:
        facts.append(Fact(
            id="dorm_osm", group="dormitory", label="Общежития на карте OSM",
            value=f"{len(dorm_osm)} {_plural(len(dorm_osm), 'здание', 'здания', 'зданий')} рядом с кампусом",
            status="confirmed", osm=[o.public() for o in dorm_osm[:8]],
            note="Данные OpenStreetMap, не фото.",
        ))
    return facts


SPORT_TYPES = [
    ("sport_gym", "Тренажёрный зал", {"fitness_centre", "fitness"}),
    ("sport_pool", "Бассейн", {"swimming_pool", "swimming"}),
    ("sport_stadium", "Стадион или поле", {"stadium", "pitch", "soccer", "football", "athletics", "track"}),
    ("sport_court", "Спортзал с площадкой", {"sports_hall", "sports_centre", "basketball", "volleyball"}),
]


def sport_facts(photos: list[Photo], campus: Campus) -> list[Fact]:
    sport = _independent([p for p in photos if p.category == "sport" and p.level != "low"])
    facts = []
    for key, label, osm_tags in SPORT_TYPES:
        ph = [p for p in sport if p.sub.get(key, 0) > 0.5]
        osm = [o for o in campus.objects if o.kind == "sport" and (o.sport or "") in osm_tags]
        n = len(ph)
        if n and osm:
            status = "confirmed"
        elif n >= 2:
            status = "weak"
        elif n or osm:
            status = "insufficient"
        else:
            status = "not_found"
        parts = []
        if n:
            parts.append(f"{n} фото")
        if osm:
            parts.append(f"{len(osm)} на карте")
        facts.append(Fact(
            id=key, group="sport", label=label, value=", ".join(parts) if parts else "не найдено", status=status,
            evidence=[_evidence(p, set()) for p in ph], osm=[o.public() for o in osm[:6]],
            note="Подтверждено, когда совпадают фото и объект OpenStreetMap." if status != "confirmed" else "Фото и карта совпадают.",
        ))
    return facts


def build_facts(photos: list[Photo], campus: Campus) -> list[dict[str, Any]]:
    return [f.public() for f in dorm_facts(photos, campus) + sport_facts(photos, campus)]
