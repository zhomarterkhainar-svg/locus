"""HTTP-клиенты сервиса: один для API источников, второй для скачивания изображений.

Пулов два намеренно. Картинок в сборке десятки, и они тяжелее ответов API: на общем пуле
загрузка фото с сайта вуза занимала все соединения, и запросы к Wikidata или Commons ждали
свободного слота - профиль собирался вдвое дольше.

Клиент httpx держит соединения, привязанные к циклу событий, поэтому клиенты хранятся по циклу:
в тестах и в скриптах ml/ циклов бывает несколько, и общий клиент из чужого цикла подвисает.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import get_settings

_clients: dict[tuple[int, str], httpx.AsyncClient] = {}


def _loop_key(kind: str) -> tuple[int, str]:
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    return loop_id, kind


def _make(kind: str) -> httpx.AsyncClient:
    s = get_settings()
    if kind == "downloads":
        return httpx.AsyncClient(
            headers={"User-Agent": s.user_agent, "Accept": "image/*,*/*;q=0.8"},
            follow_redirects=True,
            timeout=httpx.Timeout(s.download_timeout, connect=3.0),
            limits=httpx.Limits(max_connections=s.download_concurrency + 8,
                                max_keepalive_connections=s.download_concurrency),
            http2=False,
        )
    return httpx.AsyncClient(
        headers={"User-Agent": s.user_agent, "Accept-Language": "ru,kk;q=0.9,en;q=0.8"},
        follow_redirects=True,
        timeout=httpx.Timeout(8.0, connect=4.0),
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        http2=False,
    )


def _get(kind: str) -> httpx.AsyncClient:
    key = _loop_key(kind)
    c = _clients.get(key)
    if c is None or c.is_closed:
        c = _make(kind)
        _clients[key] = c
        if len(_clients) > 32:  # старые циклы уже закрыты, их клиенты соберёт сборщик мусора
            for k in [k for k in _clients if k[0] != key[0]]:
                _clients.pop(k, None)
    return c


async def client() -> httpx.AsyncClient:
    """Клиент для API источников: Wikidata, Commons, Overpass, OSRM, Open-Meteo, сайты вузов."""
    return _get("api")


async def downloads() -> httpx.AsyncClient:
    """Клиент для скачивания изображений: свой пул соединений и свой тайм-аут."""
    return _get("downloads")


async def close() -> None:
    for c in list(_clients.values()):
        try:
            await c.aclose()
        except Exception:  # noqa: BLE001  закрытие клиента из чужого цикла не должно ронять выход
            pass
    _clients.clear()


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
