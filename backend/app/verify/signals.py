"""Сигналы принадлежности фото вузу и итоговая достоверность."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ..domain import Candidate, Signal, University
from ..geo import haversine
from ..sources.osm import KIND_LABELS, Campus
from ..textnorm import normalize, to_latin
from . import calibrator

SOURCE_LABEL = {
    ("commons", "lead"): "главное фото вуза в Wikidata",
    ("commons", "category"): "файл из категории вуза на Commons",
    ("commons", "search"): "файл Commons, найденный по названию",
    ("commons", "geo"): "файл Commons с геометкой рядом",
    ("commons", "city"): "файл Commons с геометкой в городе",
    ("official", "page"): "официальный сайт вуза",
    ("flickr", "geo"): "Flickr, геометка рядом с кампусом",
    ("flickr", "search"): "Flickr, найдено по названию",
}


@dataclass
class NameMatcher:
    full: list[str]
    short: list[str]

    @classmethod
    def for_university(cls, uni: University) -> "NameMatcher":
        full, short = [], []
        for name in uni.names():
            n = normalize(name)
            if not n:
                continue
            if len(n) <= 6 and " " not in n:
                short.append(n)
            else:
                full.append(n)
                # Ядро названия без «имени ...»: «евразийский национальный университет»
                core = re.split(r"\b(имени|им|named after|атындағы)\b", n)[0].strip()
                if len(core) > 12 and core not in full:
                    full.append(core)
        for alias, expansions in _alias_index().items():
            if any(normalize(e) in full for e in expansions):
                short.append(alias)
        full += [to_latin(f) for f in full if to_latin(f) not in full]
        return cls(full=list(dict.fromkeys(full)), short=list(dict.fromkeys(short)))

    def score(self, text: str) -> tuple[float, str]:
        n = normalize(text)
        if not n:
            return 0.0, ""
        lat = to_latin(text)
        for f in self.full:
            if f in n or f in lat:
                return 1.0, f
        for s in self.short:
            if re.search(rf"(^|\s){re.escape(s)}($|\s)", n):
                return 0.6, s
        return 0.0, ""


def _alias_index() -> dict[str, list[str]]:
    from ..search.aliases import ALIASES
    return ALIASES


def geo_features(c: Candidate, uni: University, campus: Campus) -> tuple[float, float, float | None, dict | None, str]:
    """(geo, geo_far, distance_m, nearest, detail)"""
    if c.lat is None or c.lon is None:
        return 0.0, 0.0, None, None, "нет геометки"
    p = (c.lat, c.lon)
    if c.scope == "city":
        city = uni.city
        if city and city.lat is not None:
            d = haversine(p, (city.lat, city.lon))
            if d <= 10_000:
                return 0.6, 0.0, d, None, f"снято в {d / 1000:.1f} км от центра города"
            return 0.0, 1.0, d, None, f"снято в {d / 1000:.0f} км от центра города"
        return 0.0, 0.0, None, None, "нет координат города"
    d = campus.distance(p)
    near = campus.nearest(p, {"dormitory", "academic", "library", "sport", "canteen"})
    nearest = None
    if near and near[1] <= 250:
        o, od = near
        nearest = {"name": o.name or KIND_LABELS.get(o.kind, o.kind), "kind": o.kind, "kind_label": KIND_LABELS.get(o.kind, o.kind), "distance_m": round(od), "url": f"https://www.openstreetmap.org/{o.osm}"}
    other = campus.nearest(p, {"other_university"})
    if d == 0:
        return 1.0, 0.0, 0.0, nearest, "внутри границы кампуса по OpenStreetMap"
    if other and other[1] < 120 and other[1] < d:
        return 0.0, 1.0, d, None, f"ближе к другому вузу: {other[0].name or 'вуз'} ({other[1]:.0f} м)"
    if d <= 150:
        return 0.8, 0.0, d, nearest, f"{d:.0f} м от границы кампуса"
    if d <= 500:
        return 0.5, 0.0, d, nearest, f"{d:.0f} м от кампуса"
    if d <= 1500:
        return 0.15, 0.0, d, nearest, f"{d:.0f} м от кампуса"
    return 0.0, 1.0, d, None, f"снято в {d / 1000:.1f} км от кампуса"


def build(c: Candidate, uni: University, campus: Campus, matcher: NameMatcher, category_p: float,
          trash_p: float, watermark_sim: float, ref_sim: float | None) -> tuple[float, list[Signal], float | None, dict | None, float]:
    geo, geo_far, dist, nearest, geo_detail = geo_features(c, uni, campus)
    text_score, matched = matcher.score(" ".join([c.title, c.description, c.context]))
    if c.source == "official" and text_score == 0:
        text_score, matched = 0.6, "страница на сайте вуза"
    source = c.prior
    visual = 0.0 if ref_sim is None else float(np.clip((ref_sim - 0.78) / 0.14, 0.0, 1.0))
    watermark = float(np.clip((watermark_sim - 0.22) / 0.06, 0.0, 1.0))
    feats = {"geo": geo, "geo_far": geo_far, "text": text_score, "source": source, "visual": visual,
             "category": category_p, "trash": trash_p, "watermark": watermark}
    conf = calibrator.predict(feats)

    def w(key: str) -> float:
        return calibrator.weight(key)

    def note(key: str, detail: str) -> str:
        """Сигнал с нулевым весом честно помечается: калибратор на данных не нашёл в нём вклада,
        потому что крайние случаи (мусор, снимок далеко от кампуса) сервис отсекает до калибратора."""
        return detail if w(key) != 0 else f"{detail}; на итог не влияет: такие кадры отсекаются раньше"

    signals = [
        Signal("geo", "Геометка", geo if not geo_far else -1.0, w("geo") if not geo_far else -w("geo_far"), geo_detail),
        Signal("text", "Название в подписи", text_score, w("text"),
               f"найдено: «{matched}»" if matched else "название вуза в подписи и описании не найдено"),
        Signal("source", "Источник", source, w("source"), SOURCE_LABEL.get((c.source, c.origin), c.source)),
        Signal("visual", "Сходство с эталонными фото", visual, w("visual"),
               "эталонов нет" if ref_sim is None else f"косинусная близость {ref_sim:.2f}"),
        Signal("category", "Уверенность в категории", category_p, w("category"), note("category", f"вероятность {category_p:.0%}")),
        Signal("trash", "Похоже на мусор", trash_p, w("trash"), note("trash", f"вероятность {trash_p:.0%}")),
        Signal("watermark", "Водяной знак", watermark, w("watermark"),
               note("watermark", "признаки водяного знака" if watermark > 0.3 else "не обнаружен")),
    ]
    return conf, signals, dist, nearest, text_score
