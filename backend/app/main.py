"""Candid AI: HTTP API и раздача собранного фронтенда."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
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
from .vision import heads as heads_info

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


PREWARM_QUERIES = ["ЕНУ", "КазНУ", "Nazarbayev University", "KIMEP", "SDU University", "КБТУ", "Satbayev University", "Astana IT University"]


async def _prewarm() -> None:
    """Прогрев медленного OSM-кэша для частых вузов, по одному запросу раз в несколько секунд."""
    from .search.wikidata import get_university
    from .sources import osm
    await asyncio.sleep(20)
    for q in PREWARM_QUERIES:
        try:
            res = await wikidata.search(q)
            if not res["candidates"]:
                continue
            uni = await get_university(res["candidates"][0]["qid"])
            if uni.lat is None or osm.cached_campus(uni) is not None:
                continue
            await asyncio.wait_for(asyncio.shield(osm.background_task(uni)), timeout=60)
        except Exception as e:  # noqa: BLE001
            log.info("prewarm %s: %s", q, e)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warmup, daemon=True).start()
    prewarm = asyncio.create_task(_prewarm()) if settings.prewarm else None
    yield
    if prewarm:
        prewarm.cancel()
    await http.close()


app = FastAPI(
    title="Candid AI",
    version="0.2.0",
    lifespan=lifespan,
    description="Проверенный визуальный профиль университета по названию. Поток событий сборки: /api/profile/{qid}/stream (SSE).",
)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "models": models_state, "calibrator": calibrator.info(), "heads": heads_info.info(),
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


@app.get("/api/profile/{qid}/find")
async def find_in_profile(qid: str, q: str = Query(..., min_length=2, max_length=120)):
    """Поиск внутри собранного профиля текстом по эмбеддингам CLIP."""
    from .pipeline.orchestrator import ML_LOCK
    from .vision.clip_model import get_clip
    from .vision.textsearch import rank, to_english

    build_log = registry.get_fresh(qid)
    if not build_log or not build_log.embeddings:
        return JSONResponse({"error": "Профиль ещё не собран или в нём нет фото."}, status_code=404)
    english, via = await to_english(q)
    if not english:
        return {"query": q, "english": None, "results": [],
                "message": "Не понял запрос. Попробуйте проще: «бассейн», «кровати», «библиотека», «зимой»."}
    ids = list(build_log.embeddings)
    embs = np.stack([build_log.embeddings[i] for i in ids])

    def encode() -> np.ndarray:
        clip = get_clip()
        t = clip.embed_text([f"a photo of {english}", english])
        m = t.mean(axis=0)
        return m / np.linalg.norm(m)

    async with ML_LOCK:
        text_emb = await asyncio.to_thread(encode)
    results = rank(text_emb, ids, embs)
    return {"query": q, "english": english, "via": via, "results": [{"id": i, "score": s} for i, s in results]}


FEEDBACK_KINDS = {"wrong_university", "wrong_category", "duplicate", "not_a_photo", "correct"}
feedback_limiter = RateLimiter(30)


@app.post("/api/feedback")
async def feedback(request: Request):
    """Отметка «не тот вуз / не та категория». Копится в JSONL для дообучения калибратора."""
    ok, retry = feedback_limiter.allow(_client_ip(request))
    if not ok:
        return JSONResponse({"error": f"Слишком много отметок подряд, подождите {retry} с."}, status_code=429)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Ожидается JSON."}, status_code=400)
    qid, pid, kind = str(body.get("qid", "")), str(body.get("photo_id", "")), str(body.get("kind", ""))
    if not re.fullmatch(r"Q\d{1,12}", qid) or not re.fullmatch(r"[0-9a-f]{16}", pid) or kind not in FEEDBACK_KINDS:
        return JSONResponse({"error": "Неверные поля отметки."}, status_code=400)
    category = str(body.get("category", ""))[:32]
    row: dict = {"ts": int(time.time()), "qid": qid, "photo_id": pid, "kind": kind, "category": category}
    build_log = registry.get_fresh(qid)
    if build_log:
        feat = next((r for r in build_log.feature_rows if r.get("id") == pid), None)
        if feat:
            row["features"] = feat.get("features")
            row["label"] = 1 if kind == "correct" else 0 if kind == "wrong_university" else None
    path = settings.path(settings.cache_dir) / "feedback.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return JSONResponse({"error": "Не удалось сохранить отметку."}, status_code=500)
    return {"ok": True, "message": "Спасибо, отметка сохранена и попадёт в дообучение."}


dist = settings.path(settings.frontend_dist)
if dist.exists():
    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and dist.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(dist / "index.html")
