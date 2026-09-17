"""Проверки рантайма без сети: ключи ссылок, перцептивный хэш, снимок профиля, общее хранилище."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app import cache, store
from app.domain import url_key
from app.pipeline.events import EventLog
from app.pipeline.orchestrator import restore_log, snapshot_log
from app.vision.dedup import DedupIndex, PHash, phash
from app.vision.detector import _letterbox


# ---------- ссылки ----------

def test_url_key_ignores_tracking_but_keeps_meaningful_query():
    a = "https://site.kz/photo.jpg?utm_source=x&utm_campaign=y"
    b = "https://site.kz/photo.jpg"
    assert url_key(a) == url_key(b), "метки utm не меняют картинку"
    # У многих сайтов вузов картинка отдаётся скриптом: ?id= обязан различать файлы.
    assert url_key("https://site.kz/img.php?id=1") != url_key("https://site.kz/img.php?id=2")
    assert url_key("https://SITE.kz/img.php?id=1") == url_key("https://site.kz/img.php?id=1")
    assert url_key("https://site.kz/a.jpg?w=300&h=200") == url_key("https://site.kz/a.jpg?h=200&w=300")


# ---------- перцептивный хэш ----------

def _photo(seed: int, size: tuple[int, int] = (320, 240)) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (8, 8, 3), dtype=np.uint8)
    return Image.fromarray(base).resize(size, Image.BICUBIC)


def test_phash_matches_same_image_and_separates_different():
    img = _photo(1)
    assert phash(img) - phash(img.copy()) == 0
    resized = img.resize((160, 120)).resize((320, 240))
    assert phash(img) - phash(resized) <= 6, "пережатая копия должна остаться дубликатом"
    assert phash(img) - phash(_photo(2)) > 6


def test_phash_is_stable_for_jpeg_like_noise():
    img = _photo(3)
    noisy = Image.fromarray(np.clip(np.asarray(img, int) + np.random.default_rng(0).integers(-6, 6, np.asarray(img).shape), 0, 255).astype("uint8"))
    assert phash(img) - phash(noisy) <= 6


def test_dedup_index_clusters_copies():
    idx = DedupIndex()
    e1 = np.ones(8, dtype=np.float32) / np.sqrt(8)
    e2 = np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    img = _photo(4)
    cid1, kind1 = idx.add(phash(img), e1, "a")
    assert kind1 is None
    cid2, kind2 = idx.add(phash(img.copy()), e1, "b")
    assert kind2 == "exact" and cid2 == cid1
    cid3, kind3 = idx.add(phash(_photo(5)), e2, "c")
    assert kind3 is None and cid3 != cid1


def test_phash_hamming_is_symmetric():
    assert PHash(0b1011) - PHash(0b1001) == 1
    assert PHash(0) - PHash(0) == 0


# ---------- детектор: обратное преобразование координат ----------

def test_letterbox_keeps_aspect_and_offsets():
    img = Image.new("RGB", (800, 400))
    arr, r, padx, pady = _letterbox(img)
    assert arr.shape == (3, 640, 640)
    assert r == pytest.approx(0.8)
    assert padx == 0 and pady == 160
    assert 0.0 <= arr.min() and arr.max() <= 1.0


# ---------- снимок профиля для общего кэша ----------

async def test_snapshot_and_restore_round_trip():
    log = EventLog(key="Q1")
    await log.emit("university", {"qid": "Q1", "label": "Тест"})
    await log.emit("photos", {"photos": [{"id": "abc"}]})
    log.embeddings["abc"] = np.arange(4, dtype=np.float16)
    log.feature_rows = [{"id": "abc", "features": {"geo": 1.0}}]
    await log.finish()

    snap = snapshot_log(log)
    assert [e["type"] for e in snap["events"]] == ["university", "photos"]

    back = restore_log("Q1", snap)
    assert back.finished
    assert [e.type for e in back.events] == ["university", "photos"]
    assert back.feature_rows == log.feature_rows
    assert np.allclose(back.embeddings["abc"], np.arange(4))


async def test_snapshot_skips_pings():
    log = EventLog(key="Q2")
    await log.emit("ping", {})
    await log.emit("done", {"total_ms": 10})
    assert [e["type"] for e in snapshot_log(log)["events"]] == ["done"]


# ---------- общее хранилище выключено ----------

async def test_store_is_optional():
    assert store.enabled() is False
    assert store.info()["enabled"] is False
    assert await store.get_profile("Q1", 3600) is None
    assert await store.get_kv("osm", "Q1", 3600) is None
    assert await store.add_feedback({"qid": "Q1"}) is False


async def test_shared_cache_falls_back_to_disk(tmp_path, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    try:
        cache.put("osm", "Q7", {"elements": []})
        hit = await cache.get_shared("osm", "Q7", 3600)
        assert hit is not None and hit[0] == {"elements": []}
        await cache.put_shared("osm", "Q8", {"elements": [1]})
        assert cache.get("osm", "Q8", 3600)[0] == {"elements": [1]}
    finally:
        get_settings.cache_clear()
