"""Flickr API: фото под свободными лицензиями рядом с кампусом и по названию. Нужен FLICKR_API_KEY."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..config import get_settings
from ..domain import Candidate, University
from ..http import SourceError, get_json
from ..textnorm import strip_html

API = "https://www.flickr.com/services/rest/"
LICENSES = {
    "1": ("CC BY-NC-SA 2.0", "https://creativecommons.org/licenses/by-nc-sa/2.0/"),
    "2": ("CC BY-NC 2.0", "https://creativecommons.org/licenses/by-nc/2.0/"),
    "3": ("CC BY-NC-ND 2.0", "https://creativecommons.org/licenses/by-nc-nd/2.0/"),
    "4": ("CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/"),
    "5": ("CC BY-SA 2.0", "https://creativecommons.org/licenses/by-sa/2.0/"),
    "6": ("CC BY-ND 2.0", "https://creativecommons.org/licenses/by-nd/2.0/"),
    "7": ("No known copyright restrictions", "https://www.flickr.com/commons/usage/"),
    "9": ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "10": ("Public Domain Mark", "https://creativecommons.org/publicdomain/mark/1.0/"),
}
EXTRAS = "description,license,date_upload,date_taken,owner_name,geo,tags,url_z,url_c,url_m"


def enabled() -> bool:
    return bool(get_settings().flickr_api_key)


def _to_candidate(p: dict, origin: str, prior: float) -> Candidate | None:
    url = p.get("url_z") or p.get("url_c") or p.get("url_m")
    if not url:
        return None
    lic = LICENSES.get(str(p.get("license")), ("", ""))
    lat = float(p["latitude"]) if p.get("latitude") not in (None, "0", 0) else None
    lon = float(p["longitude"]) if p.get("longitude") not in (None, "0", 0) else None
    upload = p.get("dateupload")
    return Candidate(
        source="flickr", origin=origin,
        page_url=f"https://www.flickr.com/photos/{p['owner']}/{p['id']}",
        image_url=url, download_url=url,
        title=p.get("title", ""), description=strip_html((p.get("description") or {}).get("_content", ""))[:500],
        context="Теги Flickr: " + p.get("tags", ""),
        author=p.get("ownername", ""), author_url=f"https://www.flickr.com/people/{p['owner']}",
        license=lic[0], license_url=lic[1],
        published=datetime.fromtimestamp(int(upload), tz=timezone.utc).date().isoformat() if upload else None,
        taken=(p.get("datetaken") or "")[:10] or None,
        lat=lat, lon=lon, prior=prior,
    )


async def fetch(uni: University) -> list[Candidate]:
    key = get_settings().flickr_api_key
    if not key:
        raise SourceError("ключ FLICKR_API_KEY не задан")
    base = {"method": "flickr.photos.search", "api_key": key, "format": "json", "nojsoncallback": 1,
            "license": ",".join(LICENSES), "extras": EXTRAS, "content_types": 0, "safe_search": 1}
    calls = []
    if uni.lat is not None:
        calls.append(("geo", 0.4, {**base, "lat": uni.lat, "lon": uni.lon, "radius": 1, "radius_units": "km", "per_page": 60, "sort": "interestingness-desc"}))
    name = uni.labels.get("en") or uni.label
    calls.append(("search", 0.35, {**base, "text": name, "per_page": 30, "sort": "relevance"}))
    results = await asyncio.gather(*[get_json(API, params, timeout=7) for _, _, params in calls], return_exceptions=True)
    out: list[Candidate] = []
    for (origin, prior, _), r in zip(calls, results):
        if isinstance(r, BaseException):
            continue
        if r.get("stat") != "ok":
            raise SourceError(f"Flickr: {r.get('message', 'ошибка')}")
        for p in r.get("photos", {}).get("photo", []):
            cand = _to_candidate(p, origin, prior)
            if cand:
                out.append(cand)
    if not out and all(isinstance(r, BaseException) for r in results):
        raise SourceError("Flickr не отвечает")
    return out
