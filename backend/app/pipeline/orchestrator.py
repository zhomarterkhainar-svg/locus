"""Сборка визуального профиля: источники параллельно, анализ партиями по мере ответа, факты и описание в конце.

Бюджет сборки - 10 секунд (SETTINGS.total_budget). Чтобы уложиться:
* карта кампуса ищется в кэше (диск, Supabase, seed) и ждётся не дольше osm_timeout,
  а если Overpass не успел, фото проверяются по точке Wikidata и пересчитываются, когда карта придёт;
* фото анализируются партиями сразу по мере ответа каждого источника, а не в конце;
* событие `ready` отмечает момент, когда профиль уже полезен, - именно это время показывает интерфейс;
* готовый профиль целиком кладётся в Supabase, поэтому повторный запрос отдаётся за доли секунды.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .. import store
from ..config import get_settings
from ..describe.describe import collect, describe
from ..domain import Candidate, Photo, Rejected, University
from ..facts.engine import build_facts
from ..geo import haversine
from ..http import SourceError
from ..search.wikidata import get_university
from ..sources import commons, context, flickr, official_site, osm, wikipedia
from ..verify import calibrator
from ..verify.signals import NameMatcher, build as build_signals
from ..verify.stock import stock_reason
from ..vision import detector
from ..vision.categories import CATEGORIES, CITY_ALLOWED, SHELF_PREFIX, TRASH
from ..vision.clip_model import get_clip
from ..vision.dedup import DedupIndex, phash
from ..vision.loader import load_stream
from .events import EventLog

ML_LOCK = asyncio.Semaphore(1)
log = logging.getLogger("candid.pipeline")

SOURCE_LABELS = {
    "commons": "Wikimedia Commons",
    "official": "Сайт вуза",
    "flickr": "Flickr",
    "city": "Фото города (Commons)",
    "osm": "OpenStreetMap",
    "wikipedia": "Википедия",
}
REJECT_LABELS = {
    "duplicate": "дубликат",
    "trash": "не фото кампуса",
    "stock": "фотобанк",
    "small": "слишком маленькое",
    "far": "далеко от кампуса",
    "download": "не скачалось",
    "off_topic_city": "не относится к городу",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Measure:
    """Что модель увидела на фото. Не зависит от карты кампуса, поэтому переживает её позднюю загрузку."""

    candidate: Candidate
    width: int
    height: int
    category: str
    category_p: float
    trash_p: float
    watermark: float
    ref_sim: float | None
    top: list[tuple[str, float]] = field(default_factory=list)
    sub: dict[str, float] = field(default_factory=dict)


class ProfileBuild:
    def __init__(self, qid: str, log: EventLog) -> None:
        self.qid = qid
        self.log = log
        self.s = get_settings()
        self.uni: University | None = None
        self.campus = osm.Campus()
        self.campus_ready = asyncio.Event()
        self.matcher: NameMatcher | None = None
        self.dedup = DedupIndex()
        self.lock = asyncio.Lock()
        self.photos: dict[str, Photo] = {}  # по id кандидата: только представители кластеров
        self.measures: dict[str, Measure] = {}
        self.rep_of_cluster: dict[str, str] = {}
        self.seen_urls: dict[str, str] = {}  # url_key -> cluster
        self.rejected: list[Rejected] = []
        self.images: dict[str, Any] = {}  # PIL-изображения представителей общежитий для детектора
        self.shelf_counter: Counter[str] = Counter()
        self.ref_emb: list[np.ndarray] = []
        self.counts = Counter()
        self.downloads_left = self.s.max_downloads
        self._feature_rows: list[dict[str, Any]] = []
        self.context_task: asyncio.Task | None = None
        self.late_campus: osm.Campus | None = None
        self.first_photo_ms: int | None = None
        self.ready_ms: int | None = None

    async def emit(self, type_: str, data: dict[str, Any]) -> None:
        await self.log.emit(type_, data)

    async def stage(self, key: str, status: str, **extra: Any) -> None:
        await self.emit("stage", {"key": key, "status": status, **extra})

    async def progress(self) -> None:
        levels = Counter(p.level for p in self.photos.values())
        await self.emit("progress", {
            "found": self.counts["found"], "downloaded": self.counts["downloaded"], "analyzed": self.counts["analyzed"],
            "in_profile": levels["high"] + levels["medium"], "unconfirmed": levels["low"],
            "rejected": len(self.rejected), "duplicates": self.counts["duplicates"],
        })

    # ---------- основной сценарий ----------

    async def run(self) -> None:
        t0 = time.perf_counter()
        try:
            await self._run(t0)
        except Exception as e:  # noqa: BLE001
            log.exception("build %s failed", self.qid)
            await self.emit("error", {"message": "Сборка прервалась из-за внутренней ошибки. Попробуйте ещё раз.", "detail": type(e).__name__})
        finally:
            total = self.log.elapsed_ms()
            await self.emit("done", {
                "total_ms": total,
                "ready_ms": self.ready_ms,
                "first_photo_ms": self.first_photo_ms,
                "calibrator": calibrator.info(),
                "model": getattr(get_clip(), "name", "") if self.counts["analyzed"] else "",
            })
            await self.log.finish()
            asyncio.create_task(self._persist(total))

    async def _run(self, t0: float) -> None:
        await self.stage("resolve", "running")
        try:
            self.uni = await asyncio.wait_for(get_university(self.qid), timeout=self.s.resolve_timeout + 4)
        except (SourceError, asyncio.TimeoutError) as e:
            await self.stage("resolve", "error")
            await self.emit("error", {"message": f"Не удалось получить карточку вуза из Wikidata: {e or 'нет ответа'}.", "fatal": True})
            return
        uni = self.uni
        self.matcher = NameMatcher.for_university(uni)
        data = uni.public()
        if uni.lat is not None and uni.city and uni.city.lat is not None:
            data["city_distance_m"] = round(haversine((uni.lat, uni.lon), (uni.city.lat, uni.city.lon)))
        await self.emit("university", data)
        await self.stage("resolve", "done")
        await self.stage("sources", "running")

        osm_task = asyncio.create_task(self._osm())
        wiki_task = asyncio.create_task(self._wiki())
        site_task = asyncio.create_task(self._source("official", official_site.fetch))
        photo_tasks = [
            asyncio.create_task(self._source("commons", commons.fetch)),
            site_task,
            asyncio.create_task(self._source("city", commons.fetch_city)),
        ]
        if flickr.enabled():
            photo_tasks.append(asyncio.create_task(self._source("flickr", flickr.fetch)))
        else:
            await self.emit("source", {"key": "flickr", "label": SOURCE_LABELS["flickr"], "status": "skipped",
                                       "message": "ключ API не задан"})
        desc_task = asyncio.create_task(self._describe(wiki_task, site_task))

        # Основной бюджет источников. Если к его концу проверенных фото почти нет (медленная сеть,
        # тяжёлые кадры на сайте вуза), даём короткую отсрочку: пустой профиль хуже лишней секунды.
        deadline = t0 + self.s.total_budget - self.s.facts_budget
        pending = set(photo_tasks)
        extended = False
        while pending:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                if extended or self._confirmed() >= self.s.ready_min_photos:
                    break
                extended = True
                deadline += self.s.source_grace
                await self.emit("notice", {"message": "Источники отвечают медленнее обычного, ждём ещё немного, чтобы профиль не остался пустым."})
                continue
            done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await self.emit("notice", {"message": "Часть источников не успела ответить за отведённое время, профиль показан без них."})
        await self.stage("sources", "done")
        await self.stage("analyze", "done")
        await self._ready("источники ответили")
        if not osm_task.done():
            osm_task.cancel()

        await self.stage("facts", "running")
        await self._facts(t0 + self.s.total_budget)
        await self.stage("facts", "done")

        remaining = max(1.0, t0 + self.s.total_budget + 3 - time.perf_counter())
        try:
            await asyncio.wait_for(desc_task, timeout=remaining)
        except asyncio.TimeoutError:
            await self.stage("describe", "error", message="описание не успело собраться")
        if self.context_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self.context_task), timeout=max(0.5, t0 + self.s.total_budget + 4 - time.perf_counter()))
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
        await self.progress()
        self.log.feature_rows = self._feature_rows

    def _confirmed(self) -> int:
        return sum(1 for p in self.photos.values() if p.level != "low")

    async def _maybe_ready(self) -> None:
        """Профиль полезен, когда набралось достаточно подтверждённых фото в нескольких разделах.

        Это честнее, чем ждать последний источник: пользователь уже видит результат, а сборка
        продолжает добирать оставшееся до конца бюджета.
        """
        if self.ready_ms is not None:
            return
        confirmed = [p for p in self.photos.values() if p.level != "low"]
        cats = {p.category for p in confirmed}
        elapsed = self.log.elapsed_ms() / 1000
        if len(confirmed) >= self.s.ready_min_photos and len(cats) >= self.s.ready_min_categories:
            await self._ready("набралось достаточно проверенных фото")
        elif elapsed >= self.s.first_paint_target and len(confirmed) >= 3:
            await self._ready("первые проверенные фото готовы")

    async def _ready(self, why: str) -> None:
        """Момент, когда профилем уже можно пользоваться: именно он показывается как время сборки."""
        if self.ready_ms is not None:
            return
        self.ready_ms = self.log.elapsed_ms()
        levels = Counter(p.level for p in self.photos.values())
        cats = {p.category for p in self.photos.values() if p.level != "low"}
        await self.emit("ready", {"ms": self.ready_ms, "why": why, "photos": levels["high"] + levels["medium"],
                                  "categories": len(cats), "first_photo_ms": self.first_photo_ms})

    # ---------- источники ----------

    async def _osm(self) -> None:
        start = time.perf_counter()
        await self.emit("source", {"key": "osm", "label": SOURCE_LABELS["osm"], "status": "running"})
        try:
            self.campus = await osm.fetch_campus(self.uni, wait_s=self.s.osm_timeout)
            status = "ok" if (self.campus.rings or self.campus.objects) else "empty"
            msg = "граница кампуса найдена по тегу Wikidata" if self.campus.rings else "граница кампуса не размечена, используется точка из Wikidata"
            if self.campus.from_cache:
                msg += "; карта из кэша"
            await self.emit("source", {"key": "osm", "label": SOURCE_LABELS["osm"], "status": status, "count": len(self.campus.objects),
                                       "ms": int((time.perf_counter() - start) * 1000), "message": msg, "cached": self.campus.from_cache})
        except (SourceError, asyncio.TimeoutError) as e:
            if self.uni and self.uni.lat is not None:
                self.campus = osm.Campus(center=(self.uni.lat, self.uni.lon))
                self._late_campus()
            await self.emit("source", {"key": "osm", "label": SOURCE_LABELS["osm"], "status": "error",
                                       "ms": int((time.perf_counter() - start) * 1000), "message": str(e) or "нет ответа"})
        finally:
            # Порядок важен: сначала снимаем ожидание и запускаем догрузку контекста, и только
            # потом отправляем событие. Если задачу отменят по бюджету, анализ фото не зависнет.
            self.campus_ready.set()
            self.context_task = asyncio.create_task(self._context())
            await self._emit_campus()

    async def _emit_campus(self, late: bool = False) -> None:
        await self.emit("campus", {**self.campus.public(), "late": late,
                                   "university": {"lat": self.uni.lat, "lon": self.uni.lon} if self.uni else None,
                                   "city": self.uni.city.__dict__ if self.uni and self.uni.city else None})

    def _late_campus(self) -> None:
        """Overpass не успел: когда фоновая загрузка закончится, карта и оценки фото обновятся."""
        uni = self.uni
        task = osm.background_task(uni)

        async def later() -> None:
            try:
                data = await task
            except Exception:  # noqa: BLE001
                return
            if self.log.finished:
                return
            self.late_campus = osm.parse(data, uni)
            self.campus = self.late_campus
            await self._emit_campus(late=True)
            await self._rescore()

        asyncio.create_task(later())

    async def _context(self) -> None:
        """Логистика и климат: не влияют на фото, приходят отдельным событием."""
        try:
            data = await asyncio.wait_for(context.build(self.uni, self.campus), timeout=self.s.context_timeout + 3)
        except Exception as e:  # noqa: BLE001
            log.info("context failed: %s", e)
            data = {"error": "Не удалось собрать климат и маршруты."}
        await self.emit("context", data)

    async def _wiki(self) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(wikipedia.summaries(self.uni), timeout=self.s.source_timeout)
        except (SourceError, asyncio.TimeoutError):
            return []

    async def _source(self, key: str, fetcher) -> Any:
        start = time.perf_counter()
        await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "running"})
        pages = []
        try:
            result = await asyncio.wait_for(fetcher(self.uni), timeout=self.s.source_timeout)
            if isinstance(result, tuple):
                cands, pages = result
            else:
                cands = result
        except asyncio.TimeoutError:
            await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "error", "ms": int((time.perf_counter() - start) * 1000),
                                       "message": f"нет ответа за {self.s.source_timeout:.0f} с"})
            return [], []
        except SourceError as e:
            await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "error", "ms": int((time.perf_counter() - start) * 1000), "message": str(e)})
            return [], []
        except Exception as e:  # noqa: BLE001
            log.exception("source %s failed", key)
            await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "error", "ms": int((time.perf_counter() - start) * 1000),
                                       "message": f"ошибка обработки ответа ({type(e).__name__})"})
            return [], []
        await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "ok" if cands else "empty", "count": len(cands),
                                   "ms": int((time.perf_counter() - start) * 1000)})
        if cands:
            await self.stage("analyze", "running")
            try:
                await self._process(cands)
            except Exception as e:  # noqa: BLE001
                log.exception("processing %s failed", key)
                await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "error",
                                           "message": f"ошибка анализа фото ({type(e).__name__})"})
        return cands, pages

    # ---------- анализ ----------

    async def _process(self, cands: list[Candidate]) -> None:
        """Отбор кандидатов и разбор партиями: фото появляются, не дожидаясь самых медленных файлов."""
        self.counts["found"] += len(cands)
        fresh: list[Candidate] = []
        pre_rejected: list[Rejected] = []
        async with self.lock:
            for c in sorted(cands, key=lambda c: c.prior, reverse=True):
                if c.id in self.seen_urls:
                    self._attach_duplicate(self.seen_urls[c.id], c, "та же ссылка на файл")
                    continue
                reason = stock_reason(c.image_url, c.page_url)
                if reason:
                    pre_rejected.append(Rejected(c, "stock", reason))
                    self.seen_urls[c.id] = ""
                    continue
                if self.downloads_left <= 0:
                    break
                self.downloads_left -= 1
                self.seen_urls[c.id] = ""
                fresh.append(c)
            self.rejected.extend(pre_rejected)
        if pre_rejected:
            await self.emit("rejected", {"items": [r.public() for r in pre_rejected]})
        async for batch in load_stream(fresh, self.s.analyze_chunk):
            await self._analyze(batch)
        await self.progress()

    async def _analyze(self, loaded: list) -> None:
        """Одна партия скачанных файлов: модель, дубликаты, достоверность, события в интерфейс."""
        rejected: list[Rejected] = []
        ok = []
        for item in loaded:
            # Размер оцениваем по исходному файлу, а не по скачанной миниатюре: с Commons
            # для анализа берётся превью 330 px, и по нему нельзя судить, иконка это или фото.
            w = item.candidate.width or item.width
            h = item.candidate.height or item.height
            if item.image is None:
                rejected.append(Rejected(item.candidate, "download", item.error or "не скачалось"))
            elif min(w, h) < 180:
                rejected.append(Rejected(item.candidate, "small", f"{w}×{h} px, похоже на иконку или превью"))
            else:
                ok.append(item)
        self.counts["downloaded"] += len(ok)

        result: dict[str, Any] = {}
        if ok:
            async with ML_LOCK:
                result = await asyncio.to_thread(self._ml, [i.image for i in ok])
            # Ждём карту кампуса, но не дольше её собственного бюджета: без карты проверка идёт
            # по точке Wikidata, а когда карта придёт, оценки пересчитаются (_rescore).
            wait = self.s.osm_timeout - self.log.elapsed_ms() / 1000
            if wait > 0 and not self.campus_ready.is_set():
                try:
                    await asyncio.wait_for(self.campus_ready.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
        new_photos: list[Photo] = []
        updates: list[dict[str, Any]] = []
        async with self.lock:
            for idx, item in enumerate(ok):
                measured = self._measure(item, result, idx)
                if isinstance(measured, Rejected):
                    rejected.append(measured)
                    continue
                photo_or_reject = self._score(measured)
                if isinstance(photo_or_reject, Rejected):
                    rejected.append(photo_or_reject)
                    continue
                photo = photo_or_reject
                cid, kind = self.dedup.add(result["hash"][idx], result["emb"][idx], photo.candidate.id)
                self.seen_urls[photo.candidate.id] = cid
                photo.cluster = cid
                if kind is None:
                    self.rep_of_cluster[cid] = photo.candidate.id
                    self._assign_shelfmark(photo)
                    self.photos[photo.candidate.id] = photo
                    self.measures[photo.candidate.id] = measured
                    if photo.category == "dormitory":
                        self.images[photo.candidate.id] = item.image
                    if photo.candidate.origin == "lead":
                        self.ref_emb.append(result["emb"][idx])
                    self.log.embeddings[photo.candidate.id] = result["emb"][idx].astype(np.float16)
                    new_photos.append(photo)
                else:
                    rep = self.photos.get(self.rep_of_cluster[cid])
                    if rep is None:  # представитель кластера уже убран при пересчёте
                        self.rep_of_cluster[cid] = photo.candidate.id
                        self.photos[photo.candidate.id] = photo
                        self.measures[photo.candidate.id] = measured
                        self._assign_shelfmark(photo)
                        self.log.embeddings[photo.candidate.id] = result["emb"][idx].astype(np.float16)
                        new_photos.append(photo)
                        self._feature_rows.append(self._row(photo, result, idx))
                        continue
                    detail = "визуально та же фотография" if kind == "exact" else "почти тот же кадр"
                    if self._better(photo, rep):
                        photo.duplicates = rep.duplicates + [self._dup_entry(rep.candidate, detail)]
                        rep.duplicates = []
                        photo.shelfmark = rep.shelfmark
                        del self.photos[rep.candidate.id]
                        self.measures.pop(rep.candidate.id, None)
                        self.photos[photo.candidate.id] = photo
                        self.measures[photo.candidate.id] = measured
                        self.log.embeddings.pop(rep.candidate.id, None)
                        self.log.embeddings[photo.candidate.id] = result["emb"][idx].astype(np.float16)
                        self.rep_of_cluster[cid] = photo.candidate.id
                        if rep.candidate.id in self.images:
                            self.images.pop(rep.candidate.id)
                        if photo.category == "dormitory":
                            self.images[photo.candidate.id] = item.image
                        updates.append({"replaces": rep.candidate.id, "photo": photo.public()})
                        rejected.append(Rejected(rep.candidate, "duplicate", detail, duplicate_of=photo.candidate.id))
                    else:
                        rep.duplicates.append(self._dup_entry(photo.candidate, detail))
                        updates.append({"replaces": rep.candidate.id, "photo": rep.public()})
                        rejected.append(Rejected(photo.candidate, "duplicate", detail, duplicate_of=rep.candidate.id))
                    self.counts["duplicates"] += 1
                self._feature_rows.append(self._row(photo, result, idx))
            self.counts["analyzed"] += len(ok)
            self.rejected.extend(rejected)
        if new_photos:
            if self.first_photo_ms is None:
                self.first_photo_ms = self.log.elapsed_ms()
            await self.emit("photos", {"photos": [p.public() for p in new_photos]})
        for u in updates:
            await self.emit("photo_update", u)
        if rejected:
            await self.emit("rejected", {"items": [r.public() for r in rejected]})
        await self.progress()
        await self._maybe_ready()

    def _ml(self, images: list) -> dict[str, Any]:
        clip = get_clip()
        emb = clip.embed_images(images)
        probs = clip.classify(emb)
        return {
            "emb": emb,
            "probs": probs,
            "watermark": clip.watermark(emb),
            "hash": [phash(im) for im in images],
            "dorm_sub": clip.sub_scores(emb, ["dorm_room", "dorm_kitchen", "dorm_bathroom", "dorm_exterior", "dorm_corridor"]),
            "sport_sub": clip.sub_scores(emb, ["sport_gym", "sport_pool", "sport_stadium", "sport_court"]),
            "keys": clip.class_keys,
        }

    def _measure(self, item, result: dict[str, Any], idx: int) -> Measure | Rejected:
        """Что на фото: категория, мусор, водяной знак, сходство с эталоном. Карта кампуса здесь не нужна."""
        c = item.candidate
        keys: list[str] = result["keys"]
        probs = result["probs"][idx]
        n_cat = len(CATEGORIES)
        cat_probs = probs[:n_cat]
        trash_probs = probs[n_cat:]
        trash_p = float(trash_probs.sum())
        cat_idx = int(cat_probs.argmax())
        category = keys[cat_idx]
        category_p = float(cat_probs[cat_idx] / max(cat_probs.sum(), 1e-6))
        top_trash = keys[n_cat + int(trash_probs.argmax())].split(":")[1]
        if trash_p >= 0.5 and float(trash_probs.max()) > float(cat_probs.max()):
            return Rejected(c, "trash", TRASH[top_trash][0])
        if c.scope == "city" and category not in CITY_ALLOWED:
            return Rejected(c, "off_topic_city", f"похоже на «{CATEGORIES[category][0].lower()}», а не на вид города")
        if c.scope == "city":
            category = "city"

        ref_sim = None
        if self.ref_emb and c.origin != "lead":
            ref_sim = float(max(float(r @ result["emb"][idx]) for r in self.ref_emb))
        top = sorted(((keys[i], float(cat_probs[i] / max(cat_probs.sum(), 1e-6))) for i in range(n_cat)), key=lambda t: t[1], reverse=True)[:3]
        sub: dict[str, float] = {}
        if category == "dormitory":
            sub = dict(zip(["dorm_room", "dorm_kitchen", "dorm_bathroom", "dorm_exterior", "dorm_corridor"], map(float, result["dorm_sub"][idx])))
        elif category == "sport":
            sub = dict(zip(["sport_gym", "sport_pool", "sport_stadium", "sport_court"], map(float, result["sport_sub"][idx])))
        return Measure(candidate=c, width=item.width, height=item.height, category=category, category_p=category_p,
                       trash_p=trash_p, watermark=float(result["watermark"][idx]), ref_sim=ref_sim, top=top, sub=sub)

    def _score(self, m: Measure) -> Photo | Rejected:
        """Достоверность по текущей карте кампуса. Вызывается ещё раз, если карта пришла позже."""
        c = m.candidate
        category = m.category
        conf, signals, dist, nearest, text_score = build_signals(
            c, self.uni, self.campus, self.matcher, m.category_p, m.trash_p, m.watermark, m.ref_sim)
        geo_far = next((s for s in signals if s.key == "geo"), None)
        if c.scope == "campus" and geo_far and geo_far.value < 0 and text_score == 0 and c.source != "official":
            return Rejected(c, "far", geo_far.detail)
        if c.scope == "campus" and category == "city" and (text_score > 0 or (dist is not None and dist <= 150)):
            category = "campus"

        high, medium = calibrator.thresholds()
        level = "high" if conf >= high else "medium" if conf >= medium else "low"
        return Photo(
            candidate=c, retrieved=_now(), width=m.width, height=m.height, category=category,
            category_label=CATEGORIES[category][0], category_scores=m.top, confidence=conf, level=level,
            signals=signals, cluster="", nearest=nearest, distance_m=dist, sub=m.sub,
        )

    async def _rescore(self) -> None:
        """Карта кампуса пришла позже фото: пересчитываем достоверность и честно убираем чужие снимки."""
        updates: list[dict[str, Any]] = []
        removed: list[Rejected] = []
        async with self.lock:
            for pid, photo in list(self.photos.items()):
                m = self.measures.get(pid)
                if m is None:
                    continue
                scored = self._score(m)
                if isinstance(scored, Rejected):
                    del self.photos[pid]
                    self.measures.pop(pid, None)
                    self.images.pop(pid, None)
                    self.log.embeddings.pop(pid, None)
                    removed.append(scored)
                    continue
                scored.cluster = photo.cluster
                scored.shelfmark = photo.shelfmark
                scored.duplicates = photo.duplicates
                scored.boxes = photo.boxes
                if (abs(scored.confidence - photo.confidence) < 0.01 and scored.level == photo.level
                        and scored.category == photo.category):
                    continue
                self.photos[pid] = scored
                updates.append({"replaces": pid, "photo": scored.public()})
            self.rejected.extend(removed)
        for u in updates:
            await self.emit("photo_update", u)
        if removed:
            await self.emit("photo_update", {"remove": [r.candidate.id for r in removed]})
            await self.emit("rejected", {"items": [r.public() for r in removed]})
        if updates or removed:
            await self.emit("notice", {"message": f"Карта кампуса догрузилась: достоверность пересчитана "
                                                  f"({len(updates)} фото уточнено, {len(removed)} убрано из фонда)."})
            await self.progress()

    def _better(self, new: Photo, old: Photo) -> bool:
        return (new.confidence - old.confidence > 0.08) or (
            abs(new.confidence - old.confidence) <= 0.08 and new.width * new.height > 1.5 * old.width * old.height)

    @staticmethod
    def _dup_entry(c: Candidate, detail: str) -> dict[str, str]:
        return {"id": c.id, "source": c.source, "host": c.host, "page_url": c.page_url, "detail": detail}

    def _attach_duplicate(self, cluster: str, c: Candidate, detail: str) -> None:
        self.counts["duplicates"] += 1
        rep_id = self.rep_of_cluster.get(cluster)
        if rep_id and rep_id in self.photos:
            self.photos[rep_id].duplicates.append(self._dup_entry(c, detail))

    def _assign_shelfmark(self, photo: Photo) -> None:
        prefix = SHELF_PREFIX[photo.category]
        self.shelf_counter[prefix] += 1
        photo.shelfmark = f"{prefix}-{self.shelf_counter[prefix]:03d}"

    def _row(self, photo: Photo, result: dict[str, Any], idx: int) -> dict[str, Any]:
        c = photo.candidate
        return {
            "id": c.id, "university": self.qid, "source": c.source, "origin": c.origin, "scope": c.scope,
            "page_url": c.page_url, "image_url": c.image_url, "title": c.title, "category": photo.category,
            "confidence": round(photo.confidence, 4),
            "features": {s.key: s.value for s in photo.signals},
            "label": None,
        }

    # ---------- факты и описание ----------

    async def _facts(self, deadline: float) -> None:
        """Факты по фото и по карте. Детектор ограничен остатком бюджета, но факты из OpenStreetMap
        отдаются в любом случае: медленный детектор не должен уносить с собой весь блок фактов."""
        dorm = [p for p in self.photos.values() if p.category == "dormitory" and p.level != "low" and p.candidate.id in self.images]
        dorm = sorted(dorm, key=lambda p: p.confidence, reverse=True)[:self.s.max_detect]
        detector_used = False
        if dorm:
            left = deadline - time.perf_counter()
            if left >= 0.8:
                try:
                    await asyncio.wait_for(self._detect_dorm(dorm), timeout=left)
                    detector_used = True
                except asyncio.TimeoutError:
                    await self.emit("notice", {"message": "Детектор предметов не успел разобрать фото общежитий: "
                                                          "факты по кроватям показаны только по уже разобранным кадрам."})
                except Exception:  # noqa: BLE001
                    log.exception("детектор упал")
            else:
                await self.emit("notice", {"message": "Времени на разбор предметов не осталось, факты по кроватям пропущены."})
        facts = build_facts(list(self.photos.values()), self.campus)
        await self.emit("facts", {"facts": facts,
                                  "detector": detector.info()["model"] if detector_used else None})
        self.images.clear()

    async def _detect_dorm(self, dorm: list[Photo]) -> None:
        async with ML_LOCK:
            imgs = [self.images[p.candidate.id] for p in dorm]
            boxes = await asyncio.to_thread(detector.detect, imgs, 0.3)
            try:
                await asyncio.to_thread(self._bunk_stage, imgs, boxes)
            except Exception:  # noqa: BLE001
                log.exception("bunk stage failed")
        for p, b in zip(dorm, boxes):
            p.boxes = b
        await self.emit("boxes", {"items": [{"id": p.candidate.id, "boxes": p.boxes} for p in dorm if p.boxes]})

    @staticmethod
    def _bunk_stage(images: list, boxes: list[list[dict[str, Any]]]) -> None:
        """Второй этап: вырезки кроватей классифицируются как двухъярусные или обычные."""
        crops, refs = [], []
        for img, bs in zip(images, boxes):
            w, h = img.size
            for b in bs:
                if b["label"] != "кровать" or b["conf"] < 0.35:
                    continue
                x0, y0 = max(0, int((b["x"] - 0.04) * w)), max(0, int((b["y"] - 0.04) * h))
                x1, y1 = min(w, int((b["x"] + b["w"] + 0.04) * w)), min(h, int((b["y"] + b["h"] + 0.04) * h))
                if x1 - x0 < 24 or y1 - y0 < 24:
                    continue
                crops.append(img.crop((x0, y0, x1, y1)))
                refs.append(b)
        if not crops:
            return
        clip = get_clip()
        p = clip.bunk_scores(clip.embed_images(crops))
        for b, v in zip(refs, p):
            b["bunk"] = round(float(v), 3)

    async def _describe(self, wiki_task: asyncio.Task, site_task: asyncio.Task) -> None:
        await self.stage("describe", "running")
        wiki = await wiki_task
        pages: list[Any] = []
        try:
            res = await asyncio.wait_for(asyncio.shield(site_task), timeout=self.s.source_timeout + 1)
            if isinstance(res, tuple):
                pages = res[1]
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            pages = []
        sources = collect(self.uni, wiki, pages)
        result = await describe(self.uni, sources)
        await self.emit("description", result)
        await self.stage("describe", "done")

    # ---------- общий кэш ----------

    async def _persist(self, total_ms: int) -> None:
        """Готовый профиль в Supabase: повторный запрос отдаётся мгновенно даже после перезапуска."""
        if not store.enabled() or not self.photos:
            return
        try:
            snapshot = snapshot_log(self.log)
            await store.put_profile(self.qid, snapshot, total_ms, getattr(get_clip(), "name", ""))
            await store.log_query({"qid": self.qid, "ms": total_ms, "ready_ms": self.ready_ms,
                                   "photos": len(self.photos), "rejected": len(self.rejected)})
        except Exception as e:  # noqa: BLE001
            log.info("не удалось сохранить профиль в Supabase: %s", e)


def snapshot_log(log_: EventLog) -> dict[str, Any]:
    """Профиль целиком: поток событий, эмбеддинги для поиска по фото и строки признаков."""
    return {
        "version": 2,
        "events": [{"type": e.type, "data": e.data, "t": e.t} for e in log_.events if e.type != "ping"],
        "embeddings": {k: base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode()
                       for k, v in log_.embeddings.items()},
        "feature_rows": log_.feature_rows,
    }


def restore_log(qid: str, snapshot: dict[str, Any]) -> EventLog:
    from .events import Event

    log_ = EventLog(key=qid)
    log_.events = [Event(e["type"], e["data"], int(e.get("t", 0))) for e in snapshot.get("events", [])]
    log_.feature_rows = snapshot.get("feature_rows", [])
    for k, v in (snapshot.get("embeddings") or {}).items():
        try:
            log_.embeddings[k] = np.frombuffer(base64.b64decode(v), dtype=np.float16)
        except (ValueError, TypeError):
            continue
    log_.finished = True
    return log_


async def run_build(qid: str, log: EventLog) -> None:
    await ProfileBuild(qid, log).run()
