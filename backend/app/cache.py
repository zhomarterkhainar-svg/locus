"""Кэш медленных внешних данных (OSM, климат, маршруты): диск плюс общий слой в Supabase.

Кэш раскрыт в README: повторные сборки берут границу кампуса и климат отсюда, а интерфейс
показывает, что данные взяты из кэша. Чужие фото сюда не попадают.

Слоя два. Локальный - файлы в CACHE_DIR, мгновенный, но пропадает при перезапуске бесплатного
инстанса. Общий - таблица kv_cache в Supabase: переживает перезапуск и работает сразу для всех
инстансов, поэтому холодный старт не заставляет заново ждать Overpass по минуте.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .config import get_settings


def _dir() -> Path:
    d = Path(get_settings().cache_dir)
    if not d.is_absolute():
        d = get_settings().path(str(d))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(namespace: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()[:20]
    return _dir() / f"{namespace}-{digest}.json"


def _read(p: Path, ttl_s: float) -> tuple[Any, float] | None:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    age = time.time() - float(raw.get("saved", 0))
    if age > ttl_s:
        return None
    return raw.get("value"), age


def seed_path(namespace: str, key: str) -> Path:
    s = get_settings()
    digest = hashlib.sha1(key.encode()).hexdigest()[:20]
    return s.path(s.seed_cache_dir) / f"{namespace}-{digest}.json"


def get(namespace: str, key: str, ttl_s: float, seed: bool = False) -> tuple[Any, float] | None:
    """Возвращает (значение, возраст в секундах) или None. seed=True разрешает заранее собранный кэш из репозитория."""
    hit = _read(_path(namespace, key), ttl_s)
    if hit is None and seed:
        hit = _read(seed_path(namespace, key), get_settings().seed_cache_ttl_s)
    return hit


def put(namespace: str, key: str, value: Any, target: Path | None = None) -> None:
    try:
        p = target or _path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"saved": time.time(), "key": key, "value": value}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


async def get_shared(namespace: str, key: str, ttl_s: float, seed: bool = False) -> tuple[Any, float] | None:
    """Сначала диск и seed-кэш репозитория, затем общий кэш Supabase (с прогревом диска)."""
    hit = get(namespace, key, ttl_s, seed=seed)
    if hit is not None:
        return hit
    from . import store

    if not store.enabled():
        return None
    shared = await store.get_kv(namespace, key, ttl_s)
    if shared is None:
        return None
    put(namespace, key, shared[0])
    return shared


async def put_shared(namespace: str, key: str, value: Any) -> None:
    put(namespace, key, value)
    from . import store

    if store.enabled():
        await store.put_kv(namespace, key, value)
