from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import get_settings

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


async def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _lock:
            if _client is None:
                s = get_settings()
                _client = httpx.AsyncClient(
                    headers={"User-Agent": s.user_agent, "Accept-Language": "ru,kk;q=0.9,en;q=0.8"},
                    follow_redirects=True,
                    timeout=httpx.Timeout(8.0, connect=4.0),
                    limits=httpx.Limits(max_connections=60, max_keepalive_connections=30),
                    http2=False,
                )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class SourceError(Exception):
    """Источник ответил ошибкой или не ответил вовремя."""


async def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
    c = await client()
    try:
        r = await c.get(url, params=params, timeout=timeout)
    except httpx.TimeoutException as e:
        raise SourceError(f"нет ответа за {timeout:.0f} с") from e
    except httpx.HTTPError as e:
        raise SourceError(f"сетевая ошибка: {type(e).__name__}") from e
    if r.status_code == 429:
        raise SourceError("источник ограничил частоту запросов (429)")
    if r.status_code >= 400:
        raise SourceError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise SourceError("ответ не в формате JSON") from e
