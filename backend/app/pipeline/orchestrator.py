"""Сборка визуального профиля: источники параллельно, анализ партиями по мере ответа, факты и описание в конце."""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import numpy as np

from ..config import get_settings
from ..describe.describe import collect, describe
from ..domain import Candidate, Photo, Rejected, University
from ..facts.engine import build_facts
from ..geo import haversine
from ..http import SourceError
from ..search.wikidata import get_university
from ..sources import commons, flickr, official_site, osm, wikipedia
from ..verify import calibrator
from ..verify.signals import NameMatcher, build as build_signals
from ..verify.stock import stock_reason
from ..vision import detector
from ..vision.categories import CATEGORIES, CITY_ALLOWED, SHELF_PREFIX, TRASH
from ..vision.clip_model import get_clip
from ..vision.dedup import DedupIndex, phash
from ..vision.loader import load_all
from .events import EventLog

ML_LOCK = asyncio.Semaphore(1)

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
        self.rep_of_cluster: dict[str, str] = {}
        self.seen_urls: dict[str, str] = {}  # url_key -> cluster
        self.rejected: list[Rejected] = []
        self.images: dict[str, Any] = {}  # PIL-изображения представителей общежитий для детектора
        self.shelf_counter: Counter[str] = Counter()
        self.ref_emb: list[np.ndarray] = []
        self.counts = Counter()
        self.downloads_left = self.s.max_downloads
        self._feature_rows: list[dict[str, Any]] = []

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
            await self.emit("error", {"message": "Сборка прервалась из-за внутренней ошибки. Попробуйте ещё раз.", "detail": type(e).__name__})
        finally:
            await self.emit("done", {"total_ms": self.log.elapsed_ms(), "calibrator": calibrator.info(),
                                     "model": getattr(get_clip(), "name", "") if self.counts["analyzed"] else ""})
            await self.log.finish()

    async def _run(self, t0: float) -> None:
        await self.stage("resolve", "running")
        try:
            self.uni = await asyncio.wait_for(get_university(self.qid), timeout=self.s.resolve_timeout + 2)
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

        deadline = t0 + self.s.total_budget - 5.0
        pending = set(photo_tasks)
        while pending:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await self.emit("notice", {"message": "Часть источников не успела ответить за отведённое время, профиль показан без них."})
        await self.stage("sources", "done")
        await self.stage("analyze", "done")
        if not osm_task.done():
            osm_task.cancel()

        await self.stage("facts", "running")
        try:
            await asyncio.wait_for(self._facts(), timeout=max(2.0, t0 + self.s.total_budget - 1.5 - time.perf_counter()))
            await self.stage("facts", "done")
        except asyncio.TimeoutError:
            await self.stage("facts", "error", message="не успели за отведённое время")

        remaining = max(1.0, t0 + self.s.total_budget + 3 - time.perf_counter())
        try:
            await asyncio.wait_for(desc_task, timeout=remaining)
        except asyncio.TimeoutError:
            await self.stage("describe", "error", message="описание не успело собраться")
        await self.progress()
        self.log.feature_rows = self._feature_rows

    # ---------- источники ----------

    async def _osm(self) -> None:
        start = time.perf_counter()
        await self.emit("source", {"key": "osm", "label": SOURCE_LABELS["osm"], "status": "running"})
        try:
            self.campus = await asyncio.wait_for(osm.fetch_campus(self.uni), timeout=self.s.osm_timeout)
            status = "ok" if (self.campus.rings or self.campus.objects) else "empty"
            msg = "граница кампуса найдена по тегу Wikidata" if self.campus.rings else "граница кампуса не размечена, используется точка из Wikidata"
            await self.emit("source", {"key": "osm", "label": SOURCE_LABELS["osm"], "status": status, "count": len(self.campus.objects),
                                       "ms": int((time.perf_counter() - start) * 1000), "message": msg})
        except (SourceError, asyncio.TimeoutError) as e:
            if self.uni and self.uni.lat is not None:
                self.campus = osm.Campus(center=(self.uni.lat, self.uni.lon))
            await self.emit("source", {"key": "osm", "label": SOURCE_LABELS["osm"], "status": "error",
                                       "ms": int((time.perf_counter() - start) * 1000), "message": str(e) or "нет ответа"})
        finally:
            self.campus_ready.set()
            await self.emit("campus", {**self.campus.public(), "university": {"lat": self.uni.lat, "lon": self.uni.lon} if self.uni else None,
                                       "city": self.uni.city.__dict__ if self.uni and self.uni.city else None})

    async def _wiki(self) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(wikipedia.summaries(self.uni), timeout=7)
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
            await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "error", "ms": int((time.perf_counter() - start) * 1000),
                                       "message": f"ошибка обработки ответа ({type(e).__name__})"})
            return [], []
        await self.emit("source", {"key": key, "label": SOURCE_LABELS[key], "status": "ok" if cands else "empty", "count": len(cands),
                                   "ms": int((time.perf_counter() - start) * 1000)})
        if cands:
            await self.stage("analyze", "running")
            await self._process(cands)
        return cands, pages

    # ---------- анализ ----------

    async def _process(self, cands: list[Candidate]) -> None:
        self.counts["found"] += len(cands)
        fresh: list[Candidate] = []
        rejected: list[Rejected] = []
        async with self.lock:
            for c in sorted(cands, key=lambda c: c.prior, reverse=True):
                if c.id in self.seen_urls:
                    self._attach_duplicate(self.seen_urls[c.id], c, "та же ссылка на файл")
                    continue
                reason = stock_reason(c.image_url, c.page_url)
                if reason:
                    rejected.append(Rejected(c, "stock", reason))
                    self.seen_urls[c.id] = ""
                    continue
                if self.downloads_left <= 0:
                    break
                self.downloads_left -= 1
                self.seen_urls[c.id] = ""
                fresh.append(c)
        loaded = await load_all(fresh)
        ok = []
        for item in loaded:
            if item.image is None:
                rejected.append(Rejected(item.candidate, "download", item.error or "не скачалось"))
            elif min(item.width, item.height) < 180:
                rejected.append(Rejected(item.candidate, "small", f"{item.width}×{item.height} px, похоже на иконку или превью"))
            else:
                ok.append(item)
        self.counts["downloaded"] += len(ok)

        if ok:
            async with ML_LOCK:
                result = await asyncio.to_thread(self._ml, [i.image for i in ok])
            try:
                await asyncio.wait_for(self.campus_ready.wait(), timeout=max(0.5, self.s.osm_timeout - self.log.elapsed_ms() / 1000))
            except asyncio.TimeoutError:
                pass
        new_photos: list[Photo] = []
        updates: list[dict[str, Any]] = []
        async with self.lock:
            for idx, item in enumerate(ok):
                photo_or_reject = self._decide(item, result, idx)
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
                    if photo.category == "dormitory":
                        self.images[photo.candidate.id] = item.image
                    if photo.candidate.origin == "lead":
                        self.ref_emb.append(result["emb"][idx])
                    new_photos.append(photo)
                else:
                    rep = self.photos[self.rep_of_cluster[cid]]
                    detail = "визуально та же фотография" if kind == "exact" else "почти тот же кадр"
                    if self._better(photo, rep):
                        photo.duplicates = rep.duplicates + [self._dup_entry(rep.candidate, detail)]
                        rep.duplicates = []
                        photo.shelfmark = rep.shelfmark
                        del self.photos[rep.candidate.id]
                        self.photos[photo.candidate.id] = photo
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
            await self.emit("photos", {"photos": [p.public() for p in new_photos]})
        for u in updates:
            await self.emit("photo_update", u)
        if rejected:
            await self.emit("rejected", {"items": [r.public() for r in rejected]})
        await self.progress()

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

    def _decide(self, item, result: dict[str, Any], idx: int) -> Photo | Rejected:
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

        if c.scope == "city":
            if category not in CITY_ALLOWED:
                return Rejected(c, "off_topic_city", f"похоже на «{CATEGORIES[category][0].lower()}», а не на вид города")
            category = "city"

        ref_sim = None
        if self.ref_emb and c.origin != "lead":
            ref_sim = float(max(float(r @ result["emb"][idx]) for r in self.ref_emb))
        conf, signals, dist, nearest, text_score = build_signals(
            c, self.uni, self.campus, self.matcher, category_p, trash_p, float(result["watermark"][idx]), ref_sim)
        geo_far = next((s for s in signals if s.key == "geo"), None)
        if c.scope == "campus" and geo_far and geo_far.value < 0 and text_score == 0 and c.source != "official":
            return Rejected(c, "far", geo_far.detail)
        if c.scope == "campus" and category == "city" and (text_score > 0 or (dist is not None and dist <= 150)):
            category = "campus"

        high, medium = calibrator.thresholds()
        level = "high" if conf >= high else "medium" if conf >= medium else "low"
        top = sorted(((keys[i], float(cat_probs[i] / max(cat_probs.sum(), 1e-6))) for i in range(n_cat)), key=lambda t: t[1], reverse=True)[:3]
        sub: dict[str, float] = {}
        if category == "dormitory":
            sub = dict(zip(["dorm_room", "dorm_kitchen", "dorm_bathroom", "dorm_exterior", "dorm_corridor"], map(float, result["dorm_sub"][idx])))
        elif category == "sport":
            sub = dict(zip(["sport_gym", "sport_pool", "sport_stadium", "sport_court"], map(float, result["sport_sub"][idx])))
        return Photo(
            candidate=c, retrieved=_now(), width=item.width, height=item.height, category=category,
            category_label=CATEGORIES[category][0], category_scores=top, confidence=conf, level=level,
            signals=signals, cluster="", nearest=nearest, distance_m=dist, sub=sub,
        )

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

    async def _facts(self) -> None:
        dorm = [p for p in self.photos.values() if p.category == "dormitory" and p.level != "low" and p.candidate.id in self.images]
        dorm = sorted(dorm, key=lambda p: p.confidence, reverse=True)[:30]
        if dorm:
            async with ML_LOCK:
                boxes = await asyncio.to_thread(detector.detect, [self.images[p.candidate.id] for p in dorm])
            for p, b in zip(dorm, boxes):
                p.boxes = b
            await self.emit("boxes", {"items": [{"id": p.candidate.id, "boxes": p.boxes} for p in dorm if p.boxes]})
        facts = build_facts(list(self.photos.values()), self.campus)
        await self.emit("facts", {"facts": facts, "detector": "Ultralytics YOLO11s (COCO)"})
        self.images.clear()

    async def _describe(self, wiki_task: asyncio.Task, site_task: asyncio.Task) -> None:
        await self.stage("describe", "running")
        wiki = await wiki_task
        pages: list[Any] = []
        try:
            res = await asyncio.wait_for(asyncio.shield(site_task), timeout=self.s.source_timeout + 2)
            if isinstance(res, tuple):
                pages = res[1]
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pages = []
        sources = collect(self.uni, wiki, pages)
        result = await describe(self.uni, sources)
        await self.emit("description", result)
        await self.stage("describe", "done")


async def run_build(qid: str, log: EventLog) -> None:
    await ProfileBuild(qid, log).run()
