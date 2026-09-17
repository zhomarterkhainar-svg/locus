"""Официальный сайт вуза (P856): страницы про общежития, кампус, библиотеку, спорт, студенческую жизнь, галерею."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

from ..config import get_settings
from ..domain import Candidate, University
from ..http import SourceError, client
from ..textnorm import normalize

KEYWORDS = [
    (re.compile(r"(общежит|жатақхана|dormitor|hostel|residence|студгородок|студенческий городок)", re.I), 5, "dormitory"),
    (re.compile(r"(кампус|campus|инфраструктур|infrastructure|корпус)", re.I), 4, "campus"),
    (re.compile(r"(библиот|кітапхана|library)", re.I), 4, "library"),
    (re.compile(r"(спорт|sport|бассейн|pool|стадион)", re.I), 4, "sport"),
    (re.compile(r"(лаборат|laborator|зертхана)", re.I), 3, "lab"),
    (re.compile(r"(студенческая жизнь|студенттік өмір|student life|студентам|for-students|student)", re.I), 3, "student_life"),
    (re.compile(r"(галере|gallery|фото|photo|суреттер)", re.I), 3, "gallery"),
    (re.compile(r"(о университете|about|университет туралы|history)", re.I), 1, "about"),
]
SKIP_IMG = re.compile(r"(logo|icon|sprite|favicon|avatar|flag|placeholder|loader|spinner|banner-small|qr|social|arrow|button|\.svg|\.gif)", re.I)
SKIP_LINK = re.compile(r"\.(pdf|docx?|xlsx?|zip|rar|mp4|jpg|png)(\?|$)|^(mailto|tel|javascript):", re.I)
MAX_PAGES = 9
MAX_IMAGES = 36  # количество фото не преимущество: лучше меньше, но быстрее и проверенных


@dataclass
class PageText:
    url: str
    title: str
    text: str
    description: str


def _registered_domain(host: str) -> str:
    parts = host.lower().removeprefix("www.").split(".")
    return ".".join(parts[-3:]) if len(parts) > 2 and len(parts[-2]) <= 3 else ".".join(parts[-2:])


async def _get(url: str, timeout: float) -> httpx.Response | None:
    c = await client()
    try:
        r = await c.get(url, timeout=timeout)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return None
    if len(r.content) > 4_000_000:
        return None
    return r


def _meta(tree: HTMLParser, *names: str) -> str:
    for n in names:
        node = tree.css_first(f'meta[property="{n}"]') or tree.css_first(f'meta[name="{n}"]')
        if node and node.attributes.get("content"):
            return node.attributes["content"].strip()
    return ""


# Из srcset берём не самый большой файл, а самый маленький из достаточно больших: для показа
# и для анализа хватает ~800 px по ширине, а оригиналы на сайтах вузов весят по несколько мегабайт
# и на обычном интернете съедают весь бюджет сборки.
ENOUGH_WIDTH = 800


def _best_src(node) -> str:
    a = node.attributes
    srcset = a.get("srcset") or a.get("data-srcset") or ""
    if srcset:
        variants: list[tuple[int, str]] = []
        for part in srcset.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = int(re.sub(r"\D", "", bits[1]) or 0) if len(bits) > 1 else 1
            variants.append((w, bits[0]))
        if variants:
            enough = [v for v in variants if v[0] >= ENOUGH_WIDTH]
            return min(enough)[1] if enough else max(variants)[1]
    for key in ("data-src", "data-lazy-src", "data-original", "src"):
        if a.get(key) and not a[key].startswith("data:"):
            return a[key]
    return ""


def _page_images(tree: HTMLParser, page_url: str, title: str, link_text: str, published: str | None) -> list[Candidate]:
    out: list[Candidate] = []
    og = _meta(tree, "og:image", "twitter:image")
    seen: set[str] = set()
    items: list[tuple[str, str, int | None, int | None]] = []
    if og:
        items.append((og, "", None, None))
    for node in tree.css("img"):
        src = _best_src(node)
        if not src:
            continue
        a = node.attributes
        try:
            w = int(a.get("width") or 0) or None
            h = int(a.get("height") or 0) or None
        except ValueError:
            w = h = None
        if (w and w < 200) or (h and h < 150):
            continue
        items.append((src, (a.get("alt") or a.get("title") or "").strip(), w, h))
    for src, alt, w, h in items:
        absolute = urljoin(page_url, src)
        if not absolute.startswith("http") or SKIP_IMG.search(absolute) or absolute in seen:
            continue
        seen.add(absolute)
        out.append(Candidate(
            source="official", origin="page", page_url=page_url, image_url=absolute, download_url=absolute,
            title=alt or title, description=alt, context=f"Страница сайта вуза: {title}. {link_text}",
            author=urlsplit(page_url).netloc.removeprefix("www."), license="Материалы сайта вуза, права у правообладателя",
            published=published, width=w, height=h, prior=0.8,
        ))
    return out


def _published(tree: HTMLParser) -> str | None:
    value = _meta(tree, "article:published_time", "og:updated_time", "date", "pubdate")
    if not value:
        t = tree.css_first("time[datetime]")
        value = t.attributes.get("datetime", "") if t else ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value or "")
    return m.group(1) if m else None


def _text_snippet(tree: HTMLParser) -> str:
    for sel in ("main", "article", ".content", "#content", "body"):
        node = tree.css_first(sel)
        if node:
            for bad in node.css("script, style, nav, header, footer, noscript"):
                bad.decompose()
            text = re.sub(r"\s+", " ", node.text(separator=" ")).strip()
            if len(text) > 200:
                return text[:1500]
    return ""


async def fetch(uni: University) -> tuple[list[Candidate], list[PageText]]:
    if not uni.website:
        return [], []
    s = get_settings()
    home = uni.website if uni.website.startswith("http") else f"https://{uni.website}"
    host = urlsplit(home).netloc
    domain = _registered_domain(host)

    robots = RobotFileParser()
    c = await client()
    try:
        rtxt = await c.get(f"{urlsplit(home).scheme}://{host}/robots.txt", timeout=3.0)
        robots.parse(rtxt.text.splitlines() if rtxt.status_code == 200 else [])
    except httpx.HTTPError:
        robots.parse([])

    def allowed(url: str) -> bool:
        try:
            return robots.can_fetch(s.user_agent, url)
        except Exception:  # noqa: BLE001
            return True

    if not allowed(home):
        raise SourceError("robots.txt сайта запрещает обход")
    r = await _get(home, 6.0)
    if r is None:
        raise SourceError("сайт вуза не открылся")
    tree = HTMLParser(r.text)
    base = str(r.url)
    title = (tree.css_first("title").text().strip() if tree.css_first("title") else host)

    scored: dict[str, tuple[int, str]] = {}
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if not href or SKIP_LINK.search(href) or href.startswith("#"):
            continue
        url = urljoin(base, href).split("#")[0]
        if _registered_domain(urlsplit(url).netloc) != domain:
            continue
        text = normalize(a.text() or "")
        hay = f"{text} {url}"
        score = sum(w for rx, w, _ in KEYWORDS if rx.search(hay))
        if score and url.rstrip("/") != base.rstrip("/"):
            prev = scored.get(url)
            if not prev or prev[0] < score:
                scored[url] = (score, text[:80])
    ranked = sorted(scored.items(), key=lambda kv: kv[1][0], reverse=True)[:MAX_PAGES]

    candidates = _page_images(tree, base, title, "Главная страница", _published(tree))
    pages = [PageText(url=base, title=title, text=_text_snippet(tree), description=_meta(tree, "description", "og:description"))]

    async def load(url: str, link_text: str):
        if not allowed(url):
            return None
        resp = await _get(url, 5.0)
        if resp is None:
            return None
        t = HTMLParser(resp.text)
        ttl = t.css_first("title").text().strip() if t.css_first("title") else link_text
        return (_page_images(t, str(resp.url), ttl, link_text, _published(t)),
                PageText(url=str(resp.url), title=ttl, text=_text_snippet(t), description=_meta(t, "description", "og:description")))

    loaded = await asyncio.gather(*[load(u, meta[1]) for u, meta in ranked], return_exceptions=True)
    for item in loaded:
        if isinstance(item, BaseException) or item is None:
            continue
        imgs, page = item
        candidates.extend(imgs)
        pages.append(page)
    uniq: dict[str, Candidate] = {}
    for cand in candidates:
        uniq.setdefault(cand.download_url, cand)
    return list(uniq.values())[:MAX_IMAGES], pages
