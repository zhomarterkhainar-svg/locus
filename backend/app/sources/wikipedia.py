"""Википедия: краткие выдержки для описания и главное изображение статьи как эталон."""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from ..domain import University
from ..http import get_json


async def summaries(uni: University) -> list[dict[str, Any]]:
    order = [("ruwiki", "ru"), ("kkwiki", "kk"), ("enwiki", "en")]
    calls = []
    langs = []
    for site, lang in order:
        title = uni.sitelinks.get(site)
        if title:
            langs.append(lang)
            calls.append(get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}", timeout=6))
    results = await asyncio.gather(*calls, return_exceptions=True)
    out = []
    for lang, r in zip(langs, results):
        if isinstance(r, BaseException) or not r.get("extract"):
            continue
        out.append({
            "lang": lang,
            "title": r.get("title"),
            "extract": r.get("extract", ""),
            "url": r.get("content_urls", {}).get("desktop", {}).get("page") or f"https://{lang}.wikipedia.org/wiki/{quote(r.get('title', ''))}",
            "image": (r.get("originalimage") or r.get("thumbnail") or {}).get("source"),
        })
    return out
