"""Supabase (PostgreSQL + PostgREST) как общая память между инстансами.

Зачем. Бесплатный инстанс на Render засыпает и перезапускается, локальный кэш в /tmp при этом
пропадает. Supabase хранит три вещи, которые дорого собирать заново:

* `profile_cache` - готовый профиль целиком (поток событий сборки). Повторный запрос того же вуза
  отдаётся за доли секунды, даже если сервер только что поднялся;
* `kv_cache` - медленные внешние данные: границы кампуса из Overpass, климат, маршруты;
* `feedback` и `queries` - отметки пользователей для дообучения и журнал запросов для отчёта о скорости.

Работаем напрямую по REST (PostgREST) через уже поднятый httpx: отдельный SDK не нужен,
а любая ошибка Supabase не должна ломать сборку - все функции возвращают None и пишут в лог.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .config import get_settings
from .http import client

log = logging.getLogger("candid.store")

_state: dict[str, Any] = {"ok": None, "error": "", "checked": 0.0}


def enabled() -> bool:
    return get_settings().supabase_enabled


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    s = get_settings()
    h = {
        "apikey": s.supabase_key,
        "Authorization": f"Bearer {s.supabase_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _base() -> str:
    """Адрес проекта без хвоста REST.

    В Supabase адрес проекта показан в двух видах: `https://<ref>.supabase.co` в настройках
    и `https://<ref>.supabase.co/rest/v1` в примерах запросов. Со вторым вариантом в переменной
    окружения путь удваивался и PostgREST отвечал PGRST125 «Invalid path specified in request URL»,
    то есть общий кэш молча не работал. Хвост срезаем, чтобы годились оба варианта.
    """
    url = get_settings().supabase_url.strip().rstrip("/")
    for tail in ("/rest/v1", "/rest"):
        if url.endswith(tail):
            url = url[: -len(tail)].rstrip("/")
    return url


def _url(table: str) -> str:
    return f"{_base()}/rest/v1/{table}"


async def _request(method: str, table: str, **kw: Any) -> Any:
    if not enabled():
        return None
    s = get_settings()
    try:
        c = await client()
        r = await c.request(method, _url(table), headers=_headers(kw.pop("headers", None)),
                            timeout=kw.pop("timeout", s.supabase_timeout), **kw)
        if r.status_code >= 400:
            _state.update(ok=False, error=f"HTTP {r.status_code}: {r.text[:160]}", checked=time.time())
            log.info("supabase %s %s -> %s", method, table, r.status_code)
            return None
        _state.update(ok=True, error="", checked=time.time())
        if r.status_code == 204 or not r.content:
            return []
        return r.json()
    except Exception as e:  # noqa: BLE001  хранилище необязательное, падать нельзя
        _state.update(ok=False, error=f"{type(e).__name__}: {e}", checked=time.time())
        log.info("supabase %s %s failed: %s", method, table, e)
        return None


# ---------- профили целиком ----------

async def get_profile(qid: str, ttl_s: float) -> dict[str, Any] | None:
    rows = await _request("GET", "profile_cache", params={
        "qid": f"eq.{qid}", "select": "payload,updated_at,built_ms,model", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    age = _age(row.get("updated_at"))
    if age is None or age > ttl_s:
        return None
    payload = row.get("payload") or {}
    payload["cache_age_s"] = round(age)
    payload["built_ms"] = row.get("built_ms")
    return payload


async def put_profile(qid: str, payload: dict[str, Any], built_ms: int, model: str) -> None:
    await _request("POST", "profile_cache",
                   headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                   json=[{"qid": qid, "payload": payload, "built_ms": built_ms, "model": model,
                          "updated_at": _now_iso()}],
                   timeout=6.0)


# ---------- медленные данные (OSM, климат, маршруты) ----------

async def get_kv(ns: str, key: str, ttl_s: float) -> tuple[Any, float] | None:
    rows = await _request("GET", "kv_cache", params={
        "ns": f"eq.{ns}", "key": f"eq.{key}", "select": "value,updated_at", "limit": "1"})
    if not rows:
        return None
    age = _age(rows[0].get("updated_at"))
    if age is None or age > ttl_s:
        return None
    return rows[0].get("value"), age


async def put_kv(ns: str, key: str, value: Any) -> None:
    await _request("POST", "kv_cache",
                   headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                   json=[{"ns": ns, "key": key, "value": value, "updated_at": _now_iso()}],
                   timeout=6.0)


# ---------- отметки и журнал ----------

async def add_feedback(row: dict[str, Any]) -> bool:
    res = await _request("POST", "feedback", headers={"Prefer": "return=minimal"}, json=[row])
    return res is not None


async def log_query(row: dict[str, Any]) -> None:
    await _request("POST", "queries", headers={"Prefer": "return=minimal"}, json=[row])


async def recent_feedback(limit: int = 2000) -> list[dict[str, Any]]:
    rows = await _request("GET", "feedback", params={
        "select": "qid,photo_id,kind,category,features,label", "order": "id.desc", "limit": str(limit)},
        timeout=15.0)
    return rows or []


# ---------- служебное ----------

def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _age(updated_at: str | None) -> float | None:
    if not updated_at:
        return None
    from datetime import datetime, timezone

    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def info() -> dict[str, Any]:
    if not enabled():
        return {"enabled": False, "note": "SUPABASE_URL и SUPABASE_KEY не заданы: кэш только локальный."}
    # Показываем и проект, и фактический адрес запроса без ключа: по нему сразу видно,
    # что именно не так - лишний путь в переменной окружения или отсутствующая таблица.
    return {"enabled": True, "ok": _state["ok"], "error": _state["error"] or None,
            "url": get_settings().supabase_url.split("//")[-1].split(".")[0],
            "endpoint": _url("profile_cache")}
