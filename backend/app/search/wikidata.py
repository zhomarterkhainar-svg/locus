"""Wikidata: поиск вуза по названию и загрузка карточки сущности."""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

from rapidfuzz import fuzz

from ..domain import Place, University
from ..http import SourceError, get_json
from ..textnorm import has_cyrillic, normalize, to_cyrillic, to_latin
from .aliases import ALIASES

API = "https://www.wikidata.org/w/api.php"

# Типы учебных заведений (P31). Проверка по типу плюс запасная проверка по описанию.
EDU_TYPES = {
    "Q3918", "Q875538", "Q902104", "Q38723", "Q15936437", "Q62078547", "Q1371037", "Q23002054",
    "Q3354859", "Q189004", "Q1664720", "Q2467461", "Q5341295", "Q45400320", "Q13220204", "Q847027",
    "Q1143635", "Q1321960", "Q3551775", "Q1244442", "Q4671277", "Q23002039", "Q2385804", "Q4287745",
    "Q7315155", "Q1970365", "Q9842", "Q11862829", "Q3914", "Q1542938", "Q180958", "Q2143781",
}
EDU_DESC = re.compile(
    r"(университет|университеті|university|universit|институт|institute|академи|academy|колледж|college|"
    r"политехн|polytechnic|консерватор|conservatory|высшая школа|school of|business school|хогешкол|hochschule)",
    re.I,
)
HOME_REGION = {"Q232", "Q813", "Q265", "Q863", "Q874"}  # KZ, KG, UZ, TJ, TM
LANGS = ["ru", "kk", "en"]


def _first_value(claims: dict[str, Any], prop: str) -> Any:
    for c in claims.get(prop, []):
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") == "value" and c.get("rank") != "deprecated":
            return snak.get("datavalue", {}).get("value")
    return None


def _ids(claims: dict[str, Any], prop: str) -> list[str]:
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id") and c.get("rank") != "deprecated":
            out.append(v["id"])
    return out


def _label(entity: dict[str, Any]) -> str:
    labels = entity.get("labels", {})
    for lang in LANGS:
        if lang in labels:
            return labels[lang]["value"]
    return next(iter(labels.values()), {}).get("value", entity.get("id", ""))


def _description(entity: dict[str, Any]) -> str:
    d = entity.get("descriptions", {})
    for lang in LANGS:
        if lang in d:
            return d[lang]["value"]
    return ""


async def _wbgetentities(ids: list[str], props: str, timeout: float = 7.0) -> dict[str, Any]:
    out: dict[str, Any] = {}
    chunks = [ids[i:i + 50] for i in range(0, len(ids), 50)]
    results = await asyncio.gather(*[
        get_json(API, {
            "action": "wbgetentities", "ids": "|".join(chunk), "props": props,
            "languages": "|".join(LANGS), "sitefilter": "ruwiki|kkwiki|enwiki", "format": "json",
        }, timeout=timeout)
        for chunk in chunks
    ])
    for r in results:
        out.update(r.get("entities", {}))
    return out


def query_variants(query: str) -> list[str]:
    q = query.strip()
    n = normalize(q)
    variants: list[str] = [q]
    for alias in (n, n.replace(" ", "")):
        for expansion in ALIASES.get(alias, []):
            if expansion not in variants:
                variants.append(expansion)
    if len(variants) == 1 and len(n) >= 4:
        alt = to_latin(q) if has_cyrillic(q) else to_cyrillic(q)
        if alt and alt != n:
            variants.append(alt)
    return variants[:4]


_URL = re.compile(r"^(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:/.*)?$", re.I)


def site_domain(query: str) -> str | None:
    """«https://www.enu.kz/ru» -> «enu.kz». Только для запросов, похожих на адрес сайта."""
    q = query.strip()
    if " " in q or "." not in q:
        return None
    m = _URL.match(q)
    if not m:
        return None
    domain = m.group(1).lower()
    return domain if re.search(r"\.[a-z]{2,}$", domain) else None


async def _search_by_site(domain: str) -> list[str]:
    variants = [f"{p}{w}{domain}{t}" for p in ("https://", "http://") for w in ("", "www.") for t in ("/", "")]
    q = "haswbstatement:" + "|".join(f"P856={v}" for v in variants)
    data = await get_json(API, {"action": "query", "list": "search", "srsearch": q, "srlimit": 5, "format": "json"}, timeout=5.0)
    return [item["title"] for item in data.get("query", {}).get("search", [])]


def _fuzzy_query(q: str) -> str:
    words = [w for w in normalize(q).split() if w]
    return " ".join(f"{w}~" if len(w) >= 5 else w for w in words)


async def _search_ids(variant: str) -> tuple[list[str], str | None]:
    edu_filter = "haswbstatement:" + "|".join(f"P31={t}" for t in ["Q3918", "Q875538", "Q902104", "Q38723", "Q15936437", "Q1371037", "Q189004", "Q62078547", "Q45400320", "Q23002054"])
    lang = "ru" if has_cyrillic(variant) else "en"
    calls = [
        get_json(API, {"action": "wbsearchentities", "search": variant, "language": lang, "uselang": "ru",
                       "type": "item", "limit": 12, "format": "json"}, timeout=5.0),
        get_json(API, {"action": "query", "list": "search", "srsearch": f"{variant} {edu_filter}",
                       "srlimit": 12, "srinfo": "suggestion", "format": "json"}, timeout=5.0),
        get_json(API, {"action": "query", "list": "search", "srsearch": f"{_fuzzy_query(variant)} {edu_filter}",
                       "srlimit": 8, "format": "json"}, timeout=5.0),
    ]
    results = await asyncio.gather(*calls, return_exceptions=True)
    ids: list[str] = []
    suggestion = None
    for r in results:
        if isinstance(r, BaseException):
            continue
        for item in r.get("search", []):
            ids.append(item["id"])
        q = r.get("query", {})
        for item in q.get("search", []):
            ids.append(item["title"])
        suggestion = suggestion or q.get("searchinfo", {}).get("suggestion")
    if all(isinstance(r, BaseException) for r in results):
        raise SourceError("Wikidata не отвечает")
    return ids, suggestion


def _is_education(entity: dict[str, Any]) -> bool:
    types = set(_ids(entity.get("claims", {}), "P31"))
    if types & EDU_TYPES:
        return True
    desc = " ".join(d["value"] for d in entity.get("descriptions", {}).values())
    return bool(EDU_DESC.search(desc)) and not types & {"Q5"}


def _score(entity: dict[str, Any], variants: list[str]) -> float:
    names = [v["value"] for v in entity.get("labels", {}).values()]
    for vals in entity.get("aliases", {}).values():
        names.extend(a["value"] for a in vals)
    best = 0.0
    for v in variants:
        nv = normalize(v)
        lv = to_latin(v)
        for name in names:
            nn = normalize(name)
            if not nn:
                continue
            s = max(fuzz.WRatio(nv, nn), fuzz.WRatio(lv, to_latin(name)))
            if nv == nn:
                s = 100
            best = max(best, s)
    claims = entity.get("claims", {})
    if set(_ids(claims, "P17")) & HOME_REGION:
        best += 3
    best += min(len(entity.get("sitelinks", {})), 3)
    return best


async def search(query: str) -> dict[str, Any]:
    query = query.strip()
    if len(query) < 2:
        return {"query": query, "status": "too_short", "candidates": [], "suggestion": None}
    domain = site_domain(query)
    ids: list[str] = []
    if domain:
        try:
            ids = await _search_by_site(domain)
        except SourceError:
            ids = []
        if ids:
            entities = await _wbgetentities(ids[:5], "labels|descriptions|aliases|claims|sitelinks")
            variants = [_label(e) for e in entities.values() if "missing" not in e] or [domain]
        else:
            variants = [domain.split(".")[0]]
    else:
        variants = query_variants(query)
    gathered = await asyncio.gather(*[_search_ids(v) for v in variants[:3]], return_exceptions=True) if not ids else []
    suggestion = None
    errors = 0
    for g in gathered:
        if isinstance(g, BaseException):
            errors += 1
            continue
        found, sug = g
        suggestion = suggestion or sug
        for i in found:
            if i not in ids and re.fullmatch(r"Q\d+", i):
                ids.append(i)
    if gathered and errors == len(gathered):
        return {"query": query, "status": "error", "candidates": [], "suggestion": None,
                "message": "Wikidata сейчас не отвечает. Попробуйте ещё раз через минуту."}
    entities = await _wbgetentities(ids[:50], "labels|descriptions|aliases|claims|sitelinks") if ids else {}
    edu = [e for e in entities.values() if "missing" not in e and _is_education(e)]
    scored = sorted(((_score(e, variants), e) for e in edu), key=lambda t: t[0], reverse=True)
    scored = [(s, e) for s, e in scored if s >= 55][:8]

    place_ids: list[str] = []
    for _, e in scored:
        c = e.get("claims", {})
        place_ids += _ids(c, "P17")[:1] + _ids(c, "P131")[:1]
    places = await _wbgetentities(list(dict.fromkeys(place_ids)), "labels") if place_ids else {}

    candidates = []
    for s, e in scored:
        c = e.get("claims", {})
        country = _ids(c, "P17")[:1]
        city = _ids(c, "P131")[:1]
        image = _first_value(c, "P18")
        coords = _first_value(c, "P625") or {}
        candidates.append({
            "qid": e["id"],
            "label": _label(e),
            "description": _description(e),
            "country": _label(places[country[0]]) if country and country[0] in places else None,
            "city": _label(places[city[0]]) if city and city[0] in places else None,
            "image": f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(image)}?width=250" if image else None,
            "website": _first_value(c, "P856"),
            "lat": coords.get("latitude"),
            "lon": coords.get("longitude"),
            "score": round(min(s, 100.0), 1),
        })

    if not candidates:
        status = "not_found"
    elif len(candidates) == 1 or (candidates[0]["score"] >= 92 and candidates[0]["score"] - candidates[1]["score"] >= 8):
        status = "ok"
    else:
        status = "ambiguous"
    if suggestion and normalize(suggestion) == normalize(query):
        suggestion = None
    return {"query": query, "status": status, "candidates": candidates, "suggestion": suggestion}


async def get_university(qid: str) -> University:
    if not re.fullmatch(r"Q\d+", qid):
        raise SourceError("неверный идентификатор Wikidata")
    ents = await _wbgetentities([qid], "labels|descriptions|aliases|claims|sitelinks", timeout=get_timeout())
    e = ents.get(qid)
    if not e or "missing" in e:
        raise SourceError("сущность не найдена в Wikidata")
    c = e.get("claims", {})
    country_id = (_ids(c, "P17") or [None])[0]
    city_id = (_ids(c, "P131") or _ids(c, "P159") or [None])[0]
    refs = [i for i in (country_id, city_id) if i]
    places = await _wbgetentities(refs, "labels|claims") if refs else {}

    def place(pid: str | None) -> Place | None:
        if not pid or pid not in places:
            return None
        pe = places[pid]
        co = _first_value(pe.get("claims", {}), "P625") or {}
        return Place(qid=pid, label=_label(pe), lat=co.get("latitude"), lon=co.get("longitude"))

    coords = _first_value(c, "P625") or {}
    inception = _first_value(c, "P571")
    year = None
    if isinstance(inception, dict):
        m = re.match(r"[+-]?(\d{4})", inception.get("time", ""))
        year = int(m.group(1)) if m else None
    students = _first_value(c, "P2196")
    aliases = [a["value"] for vals in e.get("aliases", {}).values() for a in vals]
    return University(
        qid=qid,
        label=_label(e),
        labels={k: v["value"] for k, v in e.get("labels", {}).items()},
        aliases=aliases,
        description=_description(e),
        country=place(country_id),
        city=place(city_id),
        lat=coords.get("latitude"),
        lon=coords.get("longitude"),
        website=_first_value(c, "P856"),
        image=_first_value(c, "P18"),
        commons_category=_first_value(c, "P373"),
        inception=year,
        students=int(float(students["amount"])) if isinstance(students, dict) and students.get("amount") else None,
        sitelinks={k: v["title"] for k, v in e.get("sitelinks", {}).items()},
        instance_of=_ids(c, "P31"),
    )


def get_timeout() -> float:
    from ..config import get_settings
    return get_settings().resolve_timeout
