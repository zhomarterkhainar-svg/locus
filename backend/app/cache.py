"""Небольшой дисковый кэш JSON для медленных внешних данных (OSM, климат, маршруты).

Кэш раскрыт в README: повторные сборки берут границу кампуса и климат отсюда, а интерфейс
показывает, что данные взяты из кэша. Чужие фото сюда не попадают.
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


def get(namespace: str, key: str, ttl_s: float) -> tuple[Any, float] | None:
    """Возвращает (значение, возраст в секундах) или None."""
    try:
        p = _path(namespace, key)
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    age = time.time() - float(raw.get("saved", 0))
    if age > ttl_s:
        return None
    return raw.get("value"), age


def put(namespace: str, key: str, value: Any) -> None:
    try:
        p = _path(namespace, key)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"saved": time.time(), "key": key, "value": value}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
