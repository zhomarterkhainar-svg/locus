"""Candid AI: HTTP API и раздача собранного фронтенда."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

from . import http
from .config import get_settings
from .pipeline.events import EventLog, Registry
from .pipeline.orchestrator import run_build
from .ratelimit import RateLimiter
from .search import wikidata
from .verify import calibrator

log = logging.getLogger("candid")
settings = get_settings()
registry = Registry(settings.cache_ttl_s)
limiter = RateLimiter(settings.rate_limit_per_min)
search_cache: dict[str, tuple[float, dict]] = {}
models_state = {"clip": "loading", "detector": "loading"}


def _warmup() -> None:
    try:
        from .vision.clip_model import get_clip
        get_clip()
        models_state["clip"] = "ready"
    except Exception as e:  # noqa: BLE001
        models_state["clip"] = f"error: {e}"
    try:
        from .vision.detector import get_detector
        get_detector()
        models_state["detector"] = "ready"
    except Exception as e:  # noqa: BLE001
        models_state["detector"] = f"error: {e}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warmup, daemon=True).start()
    yield
    await http.close()


app = FastAPI(title="Candid AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "models": models_state, "calibrator": calibrator.info(),
            "sources": {"flickr": bool(settings.flickr_api_key), "gemini": bool(settings.gemini_api_key)}}


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1, max_length=160)):
    key = q.strip().lower()
    loop = asyncio.get_running_loop()
    cached = search_cache.get(key)
    if cached and loop.time() - cached[0] < 1800:
        return cached[1]
    result = await wikidata.search(q)
    if result["status"] not in ("error",):
        search_cache[key] = (loop.time(), result)
        if len(search_cache) > 2000:
            search_cache.clear()
    return result


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/profile/{qid}/stream")
async def profile_stream(qid: str, request: Request, fresh: int = 0):
    if not re.fullmatch(r"Q\d{1,12}", qid):
        return JSONResponse({"error": "Неверный идентификатор вуза."}, status_code=400)
    existing = registry.get_fresh(qid)
    replay = False
    if existing and not fresh:
        build_log = existing
        replay = existing.finished
    else:
        ok, retry = limiter.allow(_client_ip(request))
        if not ok:
            async def limited():
                yield _sse("error", {"message": f"Слишком много новых сборок подряд. Подождите {retry} с или откройте уже собранный профиль.", "fatal": True, "retry_after": retry})
                yield _sse("done", {"total_ms": 0})
            return StreamingResponse(limited(), media_type="text/event-stream")
        build_log = EventLog(key=qid)
        registry.put(build_log)
        asyncio.create_task(run_build(qid, build_log))

    async def stream():
        yield _sse("meta", {"replay": replay, "cached_at": build_log.started_wall if replay else None})
        async for ev in build_log.follow():
            if await request.is_disconnected():
                return
            if ev.type == "ping":
                yield ": ping\n\n"
                continue
            yield _sse(ev.type, {**ev.data, "t": ev.t})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/profile/{qid}/features.jsonl")
async def features(qid: str):
    build_log = registry.get_fresh(qid)
    if not build_log or not build_log.finished:
        return PlainTextResponse("Профиль ещё не собран.", status_code=404)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in build_log.feature_rows)
    return PlainTextResponse(body, media_type="application/x-ndjson",
                             headers={"Content-Disposition": f'attachment; filename="{qid}-features.jsonl"'})


dist = settings.path(settings.frontend_dist)
if dist.exists():
    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and dist.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(dist / "index.html")
