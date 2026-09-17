"""Примитивы asyncio, привязанные к текущему циклу событий.

Семафор, блокировка и фоновая задача asyncio запоминают цикл, в котором их впервые ждали.
Если такой объект лежит в глобальной переменной модуля, он переживает смену цикла - и в новом
цикле либо падает с «bound to a different event loop», либо молча висит до тайм-аута.
В боевом сервисе цикл один, но в тестах, в скриптах ml/ и в любом коде, который вызывает
asyncio.run() несколько раз, это приводит к «плавающим» зависаниям. Поэтому все общие примитивы
берутся отсюда: они хранятся по паре (цикл, ключ) и создаются заново для каждого цикла.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_registry: dict[tuple[int, str], Any] = {}
_MAX = 512


def _loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


def scoped(key: str, factory: Callable[[], T]) -> T:
    """Возвращает объект для текущего цикла, создавая его при первом обращении."""
    loop = _loop_id()
    full = (loop, key)
    value = _registry.get(full)
    if value is None:
        if len(_registry) > _MAX:
            for k in [k for k in _registry if k[0] != loop]:
                _registry.pop(k, None)
        value = factory()
        _registry[full] = value
    return value


def semaphore(key: str, limit: int) -> asyncio.Semaphore:
    return scoped(f"sem:{key}:{limit}", lambda: asyncio.Semaphore(limit))


def store(key: str) -> dict:
    """Общий на цикл словарь: например, для задач фоновой догрузки по ключу вуза."""
    return scoped(f"dict:{key}", dict)


def reset() -> None:
    _registry.clear()
