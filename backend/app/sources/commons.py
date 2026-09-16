"""Wikimedia Commons: файлы категории вуза, файлы рядом с кампусом, поиск по названию, фото города."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from ..domain import Candidate, University
from ..http import get_json
from ..textnorm import strip_html

API = "https://commons.wikimedia.org/w/api.php"
IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/tiff"}
CAMPUS_SUBCAT = re.compile(r"(build|campus|interior|dormitor|hostel|librar|sport|stadium|laborator|auditor|hall|корпус|общежит|библиот|спорт|кампус|ғимарат)", re.I)
EXT_FIELDS = "DateTimeOriginal|DateTime|ImageDescription|Artist|LicenseShortName|LicenseUrl|Categories|ObjectName|GPSLatitude|GPSLongitude"


def _meta(ext: dict[str, Any], key: str) -> str:
    return strip_html(str(ext.get(key, {}).get("value", "")))


def _iso(value: str) -> str | None:
    if not value:
        return None
    m = re.search(r"(\d{4})[-:](\d{2})[-:](\d{2})", value)
    if m:
        y, mo, d = m.groups()
        try:
            return datetime(int(y), int(mo), int(d)).date().isoformat()
        except ValueError:
            return f"{y}"
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", value)
    return m.group(1) if m else None


def _artist_url(ext: dict[str, Any]) -> str:
    m = re.search(r'href="([^"]+)"', str(ext.get("Artist", {}).get("value", "")))
    if not m:
        return ""
    href = m.group(1)
    return "https:" + href if href.startswith("//") else href


async def _category_files(category: str, limit: int) -> tuple[list[str], list[str]]:
    data = await get_json(API, {
        "action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
        "cmtype": "file|subcat", "cmlimit": 100, "format": "json",
    }, timeout=6)
    files, subcats = [], []
    for m in data.get("query", {}).get("categorymembers", []):
        if m["ns"] == 6:
            files.append(m["title"])
        elif m["ns"] == 14 and CAMPUS_SUBCAT.search(m["title"]):
            subcats.append(m["title"].removeprefix("Category:"))
    return files[:limit], subcats[:4]


async def _geo_files(lat: float, lon: float, radius: int, limit: int) -> list[str]:
    data = await get_json(API, {
        "action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": min(radius, 10000),
        "gslimit": limit, "gsnamespace": 6, "format": "json",
    }, timeout=6)
    return [g["title"] for g in data.get("query", {}).get("geosearch", [])]


async def _search_files(text: str, limit: int) -> list[str]:
    data = await get_json(API, {
        "action": "query", "list": "search", "srnamespace": 6, "srsearch": f'"{text}"', "srlimit": limit,
        "format": "json",
    }, timeout=6)
    return [s["title"] for s in data.get("query", {}).get("search", [])]


async def _imageinfo(titles: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    chunks = [titles[i:i + 50] for i in range(0, len(titles), 50)]
    results = await asyncio.gather(*[
        get_json(API, {
            "action": "query", "prop": "imageinfo|coordinates", "titles": "|".join(chunk),
            "iiprop": "url|size|mime|extmetadata|timestamp", "iiurlwidth": 500,  # стандартная ширина миниатюр Wikimedia: 640 округляется до 960 и качается втрое дольше
            "iiextmetadatafilter": EXT_FIELDS, "iiextmetadatalanguage": "ru", "format": "json",
        }, timeout=8)
        for chunk in chunks
    ], return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            continue
        for page in r.get("query", {}).get("pages", {}).values():
            if page.get("imageinfo"):
                out[page["title"]] = page
    return out


def _candidate(page: dict[str, Any], origin: str, prior: float, scope: str) -> Candidate | None:
    info = page["imageinfo"][0]
    if info.get("mime") not in IMAGE_MIME:
        return None
    ext = info.get("extmetadata", {})
    coords = (page.get("coordinates") or [{}])[0]
    title = page["title"].removeprefix("File:")
    thumb = info.get("thumburl") or info.get("url")
    return Candidate(
        source="commons",
        origin=origin,
        page_url=info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{quote(page['title'])}",
        image_url=thumb,
        download_url=thumb,
        title=_meta(ext, "ObjectName") or re.sub(r"\.\w+$", "", title),
        description=_meta(ext, "ImageDescription")[:600],
        context="Категории Commons: " + _meta(ext, "Categories").replace("|", "; "),
        author=_meta(ext, "Artist")[:120],
        author_url=_artist_url(ext),
        license=_meta(ext, "LicenseShortName"),
        license_url=_meta(ext, "LicenseUrl"),
        published=_iso(info.get("timestamp", "")),
        taken=_iso(_meta(ext, "DateTimeOriginal")),
        lat=coords.get("lat"),
        lon=coords.get("lon"),
        width=info.get("width"),
        height=info.get("height"),
        scope=scope,
        prior=prior,
    )


async def fetch(uni: University) -> list[Candidate]:
    tasks: dict[str, Any] = {}
    if uni.commons_category:
        tasks["category"] = _category_files(uni.commons_category, 45)
    if uni.lat is not None:
        tasks["geo"] = _geo_files(uni.lat, uni.lon, 900, 45)
    en = uni.labels.get("en") or uni.label
    tasks["search"] = _search_files(en, 25)
    results = dict(zip(tasks, await asyncio.gather(*tasks.values(), return_exceptions=True)))

    origin_of: dict[str, str] = {}
    cat = results.get("category")
    if cat and not isinstance(cat, BaseException):
        files, subcats = cat
        for t in files:
            origin_of.setdefault(t, "category")
        sub_results = await asyncio.gather(*[_category_files(sc, 20) for sc in subcats], return_exceptions=True)
        for sr in sub_results:
            if not isinstance(sr, BaseException):
                for t in sr[0]:
                    origin_of.setdefault(t, "category")
    for key in ("search", "geo"):
        r = results.get(key)
        if r and not isinstance(r, BaseException):
            for t in r:
                origin_of.setdefault(t, key)
    if uni.image:
        origin_of.setdefault(f"File:{uni.image}", "lead")

    if not origin_of and all(isinstance(r, BaseException) for r in results.values()):
        raise next(r for r in results.values() if isinstance(r, BaseException))

    infos = await _imageinfo(list(origin_of)[:140])
    priors = {"lead": 0.9, "category": 0.8, "search": 0.55, "geo": 0.45}
    out = []
    for title, page in infos.items():
        origin = origin_of.get(title) or origin_of.get(title.replace(" ", "_"), "geo")
        cand = _candidate(page, origin, priors[origin], "campus")
        if cand:
            out.append(cand)
    return out


async def fetch_city(uni: University) -> list[Candidate]:
    city = uni.city
    if not city or city.lat is None:
        return []
    titles = await _geo_files(city.lat, city.lon, 2500, 40)
    infos = await _imageinfo(titles)
    out = []
    for page in infos.values():
        cand = _candidate(page, "city", 0.5, "city")
        if cand:
            out.append(cand)
    return out
