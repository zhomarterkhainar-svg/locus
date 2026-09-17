"""Синхронный клиент Wikimedia Commons для сборки обучающих данных (скрипты ml/*).

Соблюдает правила Wikimedia: User-Agent с контактом, maxlag, повтор при 429/5xx с паузой,
стандартные ширины миниатюр (330/500 px).
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

import httpx

API = "https://commons.wikimedia.org/w/api.php"
UA = f"CandidAI-trainer/0.2 (LOCUS Hackathon 2026; +{os.environ.get('CONTACT', 'https://github.com/zhomarterkhainar-svg/locus')})"
IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_PARALLEL_CATS = 6  # одновременных запросов списка категорий: больше Wikimedia уже считает грубостью


class Commons:
    def __init__(self, timeout: float = 30.0) -> None:
        self.http = httpx.Client(headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True)

    def get(self, params: dict[str, Any], tries: int = 8) -> dict[str, Any]:
        """Запрос к API с повторами. Wikimedia при перегрузке отвечает HTML-страницей ошибки,
        поэтому не-JSON тоже считается поводом повторить, а не падением скрипта."""
        params = {**params, "format": "json", "maxlag": 5}
        delay = 2.0
        last = ""
        for attempt in range(tries):
            try:
                r = self.http.get(API, params=params)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    raise httpx.HTTPStatusError("retry", request=r.request, response=r)
                if "json" not in r.headers.get("content-type", ""):
                    last = f"ответ не JSON ({r.headers.get('content-type', '?')})"
                    raise ValueError(last)
                data = r.json()
                if data.get("error", {}).get("code") == "maxlag":
                    raise httpx.HTTPError("maxlag")
                return data
            except (httpx.HTTPError, ValueError) as e:
                last = last or type(e).__name__
                if attempt == tries - 1:
                    raise RuntimeError(f"Commons API не отвечает: {last}") from e
                time.sleep(delay)
                delay = min(delay * 2, 60)
        return {}

    def members(self, category: str, types: str = "file|subcat") -> Iterator[dict[str, Any]]:
        params: dict[str, Any] = {"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
                                  "cmtype": types, "cmlimit": 500}
        while True:
            data = self.get(params)
            yield from data.get("query", {}).get("categorymembers", [])
            cont = data.get("continue")
            if not cont:
                return
            params.update(cont)

    def files_in_tree(self, category: str, depth: int, limit: int, skip_subcat: set[str] | None = None) -> list[tuple[str, str]]:
        """Файлы категории и подкатегорий (поиск в ширину). Возвращает [(title, путь категорий)].

        Уровни дерева обходятся параллельно: у крупных категорий Commons («Campuses», «Libraries»)
        сотни подкатегорий, и последовательный обход занимал минуты на каждый класс.
        """
        out: list[tuple[str, str]] = []
        seen_cats = {category}
        frontier = [(category, category, 0)]
        while frontier and len(out) < limit:
            level, frontier = frontier[:MAX_PARALLEL_CATS], frontier[MAX_PARALLEL_CATS:]

            def one(item: tuple[str, str, int]) -> tuple[tuple[str, str, int], list[dict[str, Any]]]:
                cat, _, _ = item
                try:
                    return item, list(self.members(cat))
                except httpx.HTTPError:
                    return item, []

            with ThreadPoolExecutor(min(MAX_PARALLEL_CATS, len(level))) as ex:
                results = list(ex.map(one, level))
            for (cat, path, d), members in results:
                for m in members:
                    if m["ns"] == 6 and len(out) < limit:
                        out.append((m["title"], path))
                    elif m["ns"] == 14 and d < depth:
                        sub = m["title"].removeprefix("Category:")
                        if sub in seen_cats or (skip_subcat and any(s in sub.lower() for s in skip_subcat)):
                            continue
                        seen_cats.add(sub)
                        frontier.append((sub, f"{path} > {sub}", d + 1))
        return out

    def imageinfo(self, titles: list[str], width: int = 330) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(titles), 50):
            chunk = titles[i:i + 50]
            data = self.get({"action": "query", "prop": "imageinfo|coordinates", "titles": "|".join(chunk),
                             "iiprop": "url|size|mime|extmetadata|timestamp", "iiurlwidth": width,
                             "iiextmetadatafilter": "ImageDescription|Artist|LicenseShortName|ObjectName|DateTimeOriginal|Categories",
                             "iiextmetadatalanguage": "ru"})
            for page in data.get("query", {}).get("pages", {}).values():
                if page.get("imageinfo"):
                    out[page["title"]] = page
        return out

    def download(self, url: str, tries: int = 5) -> bytes | None:
        delay = 2.0
        for _ in range(tries):
            try:
                r = self.http.get(url)
            except httpx.HTTPError:
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                return r.content
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get("retry-after", delay)))
                delay = min(delay * 2, 60)
                continue
            return None
        return None
