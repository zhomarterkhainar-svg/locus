"""Скачивание изображений для анализа. Файлы держатся только в памяти на время сборки профиля."""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

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
        img = await asyncio.to_thread(_decode, bytes(buf))
    except Exception:  # noqa: BLE001
        return Loaded(cand, None, error="не удалось прочитать изображение")
    w, h = img.info.pop("orig_size", img.size)
    return Loaded(cand, img, width=w, height=h)


def _decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    orig = img.size
    img.draft("RGB", (800, 800))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((640, 640))
    img.info["orig_size"] = orig
    return img


async def load_all(cands: list[Candidate]) -> list[Loaded]:
    sem = asyncio.Semaphore(get_settings().download_concurrency)
    return await asyncio.gather(*[_load_one(c, sem) for c in cands])
