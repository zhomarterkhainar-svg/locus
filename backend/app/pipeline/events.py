"""Журнал событий сборки профиля: несколько зрителей подписываются на одну сборку, готовые сборки кэшируются."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class Event:
    type: str
    data: dict[str, Any]
    t: int  # мс от начала сборки


@dataclass
class EventLog:
    key: str
    started: float = field(default_factory=time.perf_counter)
    started_wall: float = field(default_factory=time.time)
    events: list[Event] = field(default_factory=list)
    finished: bool = False
    feature_rows: list[dict[str, Any]] = field(default_factory=list)
    embeddings: dict[str, Any] = field(default_factory=dict)  # id фото в фонде -> эмбеддинг CLIP (float16)
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    async def emit(self, type_: str, data: dict[str, Any]) -> None:
        async with self._cond:
            self.events.append(Event(type_, data, self.elapsed_ms()))
            self._cond.notify_all()

    async def finish(self) -> None:
        async with self._cond:
            self.finished = True
            self._cond.notify_all()

    async def follow(self) -> AsyncIterator[Event]:
        i = 0
        while True:
            async with self._cond:
                while i >= len(self.events) and not self.finished:
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        break
                batch = self.events[i:]
                done = self.finished and i + len(batch) >= len(self.events)
            if not batch and not done:
                yield Event("ping", {}, self.elapsed_ms())
                continue
            for ev in batch:
                yield ev
            i += len(batch)
            if done:
                return


class Registry:
    def __init__(self, ttl_s: int) -> None:
        self.ttl = ttl_s
        self.logs: dict[str, EventLog] = {}

    def get_fresh(self, key: str) -> EventLog | None:
        log = self.logs.get(key)
        if not log:
            return None
        if log.finished and time.time() - log.started_wall > self.ttl:
            del self.logs[key]
            return None
        return log

    def put(self, log: EventLog) -> None:
        self.logs[log.key] = log
        if len(self.logs) > 200:
            oldest = sorted((l for l in self.logs.values() if l.finished), key=lambda l: l.started_wall)[:50]
            for l in oldest:
                self.logs.pop(l.key, None)
