"""Скачивание изображений для анализа. Файлы держатся только в памяти на время сборки профиля."""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import AsyncIterator
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

from .. import concurrency
from ..config import get_settings
from ..domain import Candidate
from ..http import downloads

Image.MAX_IMAGE_PIXELS = 60_000_000


@dataclass
class Loaded:
    candidate: Candidate
    image: Image.Image | None
    width: int = 0
    height: int = 0
    error: str = ""


# Не больше нескольких одновременных запросов к одному хосту: иначе сайт вуза отдаёт
# десяток тяжёлых кадров медленнее, чем отдал бы по очереди, и это вежливее к источнику.
# Декодирование картинки держит GIL, и десяток параллельных декодов подвешивает цикл событий:
# ответы источников и поток событий в браузер начинают опаздывать, поэтому оно тоже ограничено.


# Отдача картинок у Wikimedia и Flickr - это CDN, рассчитанный на параллельные запросы;
# сайту вуза столько же запросов сразу делать и невежливо, и медленнее для нас.
CDN_HOSTS = ("wikimedia.org", "wikipedia.org", "staticflickr.com", "flickr.com")


def _host_sem(url: str) -> asyncio.Semaphore:
    host = urlsplit(url).netloc.lower()
    s = get_settings()
    limit = s.cdn_host_downloads if host.endswith(CDN_HOSTS) else s.per_host_downloads
    return concurrency.semaphore(f"host:{host}", limit)


def _decoder() -> asyncio.Semaphore:
    return concurrency.semaphore("decode", get_settings().decode_concurrency)


async def _load_one(cand: Candidate, sem: asyncio.Semaphore) -> Loaded:
    s = get_settings()
    c = await downloads()
    async with sem, _host_sem(cand.download_url):
        try:
            async with c.stream("GET", cand.download_url, timeout=s.download_timeout,
                                headers={"Referer": cand.page_url}) as r:
                if r.status_code != 200:
                    return Loaded(cand, None, error=f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "")
                if ctype and not ctype.startswith("image/") and "octet-stream" not in ctype:
                    return Loaded(cand, None, error="не изображение")
                if "svg" in ctype or "gif" in ctype:
                    return Loaded(cand, None, error="векторная графика или анимация")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > s.max_image_bytes:
                        return Loaded(cand, None, error="файл слишком большой")
        except httpx.TimeoutException:
            return Loaded(cand, None, error="не скачалось вовремя")
        except httpx.HTTPError as e:
            return Loaded(cand, None, error=f"сетевая ошибка {type(e).__name__}")
        except Exception as e:  # noqa: BLE001
            return Loaded(cand, None, error=f"ошибка загрузки {type(e).__name__}")
    try:
        async with _decoder():
            img = await asyncio.to_thread(_decode, bytes(buf), s.analyze_side)
    except Exception:  # noqa: BLE001
        return Loaded(cand, None, error="не удалось прочитать изображение")
    w, h = img.info.pop("orig_size", img.size)
    return Loaded(cand, img, width=w, height=h)


def _decode(data: bytes, side: int) -> Image.Image:
    """Декодируем сразу в нужном масштабе: draft() у JPEG пропускает лишние коэффициенты DCT,
    поэтому большой кадр читается в разы быстрее, а для анализа хватает стороны side."""
    img = Image.open(io.BytesIO(data))
    orig = img.size
    img.draft("RGB", (side, side))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > side:
        img.thumbnail((side, side), Image.BILINEAR)
    img.info["orig_size"] = orig
    return img


async def load_all(cands: list[Candidate]) -> list[Loaded]:
    sem = asyncio.Semaphore(get_settings().download_concurrency)
    return await asyncio.gather(*[_load_one(c, sem) for c in cands])


async def load_stream(cands: list[Candidate], chunk: int = 12) -> AsyncIterator[list[Loaded]]:
    """Отдаёт скачанное партиями, не дожидаясь самых медленных файлов.

    Благодаря этому первые проверенные фото появляются через секунду после ответа источника,
    а если сборка упирается в бюджет времени, уже разобранные партии остаются в профиле.
    """
    if not cands:
        return
    sem = asyncio.Semaphore(get_settings().download_concurrency)
    tasks = [asyncio.create_task(_load_one(c, sem)) for c in cands]
    buf: list[Loaded] = []
    # Первая партия вдвое меньше: первые проверенные фото появляются в интерфейсе заметно раньше,
    # дальше партии крупнее, чтобы не гонять модель на мелких батчах.
    size = max(4, chunk // 2)
    try:
        for fut in asyncio.as_completed(tasks):
            buf.append(await fut)
            if len(buf) >= size:
                yield buf
                buf = []
                size = chunk
        if buf:
            yield buf
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
