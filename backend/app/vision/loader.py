"""Скачивание изображений для анализа. Файлы держатся только в памяти на время сборки профиля."""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from PIL import Image, ImageOps

from ..config import get_settings
from ..domain import Candidate
from ..http import client

Image.MAX_IMAGE_PIXELS = 60_000_000


@dataclass
class Loaded:
    candidate: Candidate
    image: Image.Image | None
    width: int = 0
    height: int = 0
    error: str = ""


async def _load_one(cand: Candidate, sem: asyncio.Semaphore) -> Loaded:
    s = get_settings()
    c = await client()
    async with sem:
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
    try:
        for fut in asyncio.as_completed(tasks):
            buf.append(await fut)
            if len(buf) >= chunk:
                yield buf
                buf = []
        if buf:
            yield buf
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
