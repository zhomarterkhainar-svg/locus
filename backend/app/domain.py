"""Внутренние структуры данных пайплайна."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit


# Параметры-метки, которые не меняют саму картинку: их выбрасываем, остальные оставляем,
# иначе все изображения сайтов вида /image.php?id=42 слиплись бы в один «дубликат».
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
                   "fbclid", "gclid", "yclid", "_", "v", "ver", "t", "ts", "cache", "rand"}


def url_key(url: str) -> str:
    """Ключ URL без протокола и меток слежения, чтобы ловить одну картинку по разным ссылкам."""
    parts = urlsplit(url)
    query = "&".join(sorted(
        f"{k}={v}" for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS))
    return hashlib.sha1(f"{parts.netloc.lower()}{parts.path}?{query}".encode()).hexdigest()[:16]


@dataclass
class Place:
    qid: str
    label: str
    lat: float | None = None
    lon: float | None = None


@dataclass
class University:
    qid: str
    label: str
    labels: dict[str, str]
    aliases: list[str]
    description: str
    country: Place | None
    city: Place | None
    lat: float | None
    lon: float | None
    website: str | None
    image: str | None  # имя файла Commons (P18)
    commons_category: str | None
    inception: int | None
    students: int | None
    sitelinks: dict[str, str]
    instance_of: list[str] = field(default_factory=list)
    coords_source: str = "Wikidata"

    def names(self) -> list[str]:
        seen: list[str] = []
        for n in [self.label, *self.labels.values(), *self.aliases]:
            if n and n not in seen:
                seen.append(n)
        return seen

    def public(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "label": self.label,
            "labels": self.labels,
            "description": self.description,
            "country": self.country.__dict__ if self.country else None,
            "city": self.city.__dict__ if self.city else None,
            "lat": self.lat,
            "lon": self.lon,
            "website": self.website,
            "inception": self.inception,
            "students": self.students,
            "wikidata_url": f"https://www.wikidata.org/wiki/{self.qid}",
            "coords_source": self.coords_source,
        }


@dataclass
class Candidate:
    source: str  # commons | official | flickr | wikipedia
    origin: str  # category | geo | search | city | page | lead
    page_url: str
    image_url: str  # что показываем (превью у источника)
    download_url: str  # что скачиваем для анализа
    title: str = ""
    description: str = ""
    context: str = ""  # категории, заголовок страницы, текст ссылки
    author: str = ""
    author_url: str = ""
    license: str = ""
    license_url: str = ""
    published: str | None = None
    taken: str | None = None
    lat: float | None = None
    lon: float | None = None
    width: int | None = None
    height: int | None = None
    scope: str = "campus"  # campus | city
    prior: float = 0.5  # доверие к способу, которым кандидат найден

    @property
    def id(self) -> str:
        return url_key(self.download_url)

    @property
    def host(self) -> str:
        return urlsplit(self.page_url).netloc.lower().removeprefix("www.")


@dataclass
class Signal:
    key: str
    label: str
    value: float
    weight: float
    detail: str

    @property
    def contribution(self) -> float:
        return round(self.value * self.weight, 3)


@dataclass
class Photo:
    candidate: Candidate
    retrieved: str
    width: int
    height: int
    category: str
    category_label: str
    category_scores: list[tuple[str, float]]
    confidence: float
    level: str  # high | medium | low
    signals: list[Signal]
    cluster: str
    shelfmark: str = ""
    nearest: dict[str, Any] | None = None
    distance_m: float | None = None
    duplicates: list[dict[str, str]] = field(default_factory=list)
    boxes: list[dict[str, Any]] = field(default_factory=list)
    sub: dict[str, float] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        c = self.candidate
        return {
            "id": c.id,
            "shelfmark": self.shelfmark,
            "source": c.source,
            "origin": c.origin,
            "host": c.host,
            "page_url": c.page_url,
            "image_url": c.image_url,
            "title": c.title,
            "description": c.description[:400],
            "author": c.author,
            "author_url": c.author_url,
            "license": c.license,
            "license_url": c.license_url,
            "published": c.published,
            "taken": c.taken,
            "retrieved": self.retrieved,
            "lat": c.lat,
            "lon": c.lon,
            "width": c.width or self.width,
            "height": c.height or self.height,
            "scope": c.scope,
            "category": self.category,
            "category_label": self.category_label,
            "category_scores": [{"key": k, "p": round(p, 3)} for k, p in self.category_scores],
            "confidence": round(self.confidence, 3),
            "level": self.level,
            "signals": [
                {"key": s.key, "label": s.label, "value": round(s.value, 3), "weight": s.weight,
                 "contribution": s.contribution, "detail": s.detail}
                for s in self.signals
            ],
            "cluster": self.cluster,
            "nearest": self.nearest,
            "distance_m": None if self.distance_m is None else round(self.distance_m),
            "duplicates": self.duplicates,
            "boxes": self.boxes,
        }


@dataclass
class Rejected:
    candidate: Candidate
    reason: str  # duplicate | trash | stock | small | far | download | other_city
    detail: str
    duplicate_of: str | None = None

    def public(self) -> dict[str, Any]:
        c = self.candidate
        return {
            "id": c.id,
            "source": c.source,
            "host": c.host,
            "page_url": c.page_url,
            "image_url": c.image_url,
            "title": c.title,
            "reason": self.reason,
            "detail": self.detail,
            "duplicate_of": self.duplicate_of,
        }
