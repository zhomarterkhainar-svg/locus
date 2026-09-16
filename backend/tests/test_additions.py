"""Тесты доработок: кэш OSM и фоновая догрузка, климат и маршруты, головы, поиск внутри профиля, двухъярусные кровати."""
import asyncio
import json

import numpy as np
import pytest
import respx
from httpx import Response

import api_fixtures as fx
from app import cache
from app.config import get_settings
from app.domain import Candidate, Photo
from app.facts.engine import dorm_facts
from app.search.wikidata import site_domain
from app.sources import context, osm
from app.vision import heads as heads_mod
from app.vision.textsearch import lexicon_translate, rank
from test_units import enu


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "cache_dir", str(tmp_path / "cache"))
    osm._inflight.clear()
    yield


def test_cache_roundtrip_and_ttl():
    cache.put("x", "k", {"a": 1})
    assert cache.get("x", "k", 60)[0] == {"a": 1}
    assert cache.get("x", "k", -1) is None
    assert cache.get("x", "other", 60) is None


def test_osm_amenities_parsed_and_hidden_from_objects():
    data = json.loads(json.dumps(fx.OVERPASS))
    data["elements"] += [
        {"type": "node", "id": 10, "lat": 51.1590, "lon": 71.4660, "tags": {"highway": "bus_stop", "name": "ЕНУ"}},
        {"type": "node", "id": 11, "lat": 51.1591, "lon": 71.4661, "tags": {"shop": "supermarket", "name": "Magnum"}},
        {"type": "node", "id": 12, "lat": 51.1592, "lon": 71.4662, "tags": {"amenity": "pharmacy"}},
    ]
    campus = osm.parse(data, enu())
    pub = campus.public()
    assert {a["kind"] for a in pub["amenities"]} == {"transport", "shop", "pharmacy"}
    assert all(o["kind"] not in osm.AMENITY_KINDS for o in pub["objects"])
    summary = context.amenities_summary(campus, (51.1602, 71.4648))
    assert summary["counts"] == {"transport": 1, "shop": 1, "pharmacy": 1}


async def test_osm_race_first_valid_mirror_and_cache():
    with respx.mock(assert_all_called=False) as r:
        r.post("https://overpass-api.de/api/interpreter").mock(return_value=Response(504, text="<html>timeout</html>"))
        r.post("https://overpass.kumi.systems/api/interpreter").mock(return_value=Response(200, json=fx.OVERPASS))
        r.post("https://maps.mail.ru/osm/tools/overpass/api/interpreter").mock(return_value=Response(200, text="not json"))
        r.post("https://overpass.private.coffee/api/interpreter").mock(return_value=Response(429))
        campus = await osm.fetch_campus(enu(), wait_s=5)
    assert campus.rings and not campus.from_cache
    again = await osm.fetch_campus(enu(), wait_s=0.01)  # сеть не нужна: из кэша
    assert again.from_cache and again.rings


async def test_osm_background_completion_after_timeout():
    async def slow(request):
        await asyncio.sleep(0.3)
        return Response(200, json=fx.OVERPASS)

    with respx.mock(assert_all_called=False) as r:
        r.post(url__regex=r".*interpreter").mock(side_effect=slow)
        with pytest.raises(Exception) as exc:
            await osm.fetch_campus(enu(), wait_s=0.05)
        assert "фоне" in str(exc.value)
        await asyncio.sleep(0.5)
    assert osm.cached_campus(enu()) is not None


def test_climate_aggregation():
    days = {"time": ["2024-01-01", "2024-01-02", "2024-07-01"], "temperature_2m_mean": [-10.0, -14.0, 22.0],
            "temperature_2m_min": [-15.0, -20.0, 15.0], "temperature_2m_max": [-5.0, -8.0, 28.0],
            "precipitation_sum": [1.0, 2.0, 0.5], "snowfall_sum": [1.0, 0.0, 0.0]}
    months = context.aggregate_climate(days)
    jan = next(m for m in months if m["month"] == 1)
    assert jan["t_mean"] == -12.0 and jan["precip_mm"] == 3 and jan["snow_days"] == 1
    assert [m["month"] for m in months] == [1, 7]


async def test_context_build_routes_and_winter_walk():
    daily = {"time": [f"2024-{m:02d}-01" for m in range(1, 13)], "temperature_2m_mean": [-14 + 3 * i for i in range(12)],
             "temperature_2m_min": [-20 + 3 * i for i in range(12)], "temperature_2m_max": [-8 + 3 * i for i in range(12)],
             "precipitation_sum": [10] * 12, "snowfall_sum": [0] * 12}
    route = {"code": "Ok", "routes": [{"distance": 1200.0, "duration": 900.0, "geometry": {"coordinates": [[71.465, 51.156], [71.4648, 51.1602]]}}]}
    campus = osm.parse(fx.OVERPASS, enu())
    with respx.mock(assert_all_called=False) as r:
        r.get(url__startswith="https://archive-api.open-meteo.com").mock(return_value=Response(200, json={"daily": daily}))
        r.get(url__startswith="https://routing.openstreetmap.de").mock(return_value=Response(200, json=route))
        out = await context.build(enu(), campus)
    assert out["climate"]["coldest"]["label"] == "янв"
    keys = {x["key"] for x in out["routes"]}
    assert {"city_car", "city_foot", "dorm_0"} <= keys
    assert out["winter_walk"] == {"minutes": 15, "month": "янв", "t_mean": -14}
    assert out["routes"][0]["line"][0] == [51.156, 71.465]


async def test_context_survives_source_errors():
    with respx.mock(assert_all_called=False) as r:
        r.get(url__startswith="https://archive-api.open-meteo.com").mock(return_value=Response(503))
        r.get(url__startswith="https://routing.openstreetmap.de").mock(return_value=Response(503))
        out = await context.build(enu(), osm.Campus())
    assert out["climate"] is None and out["routes"] == [] and "climate_error" in out


def test_heads_load_blend_and_model_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "heads_dir", str(tmp_path))
    keys = ["a", "b", "c"]
    W = np.eye(3, 4, dtype=np.float32) * 10
    (tmp_path / "category.json").write_text(json.dumps({"keys": keys, "W": W.tolist(), "b": [0, 0, 0]}))
    (tmp_path / "heads.json").write_text(json.dumps({"model": "M/1", "heads": {"category": {"alpha": 0.5}}}))
    assert heads_mod.load_heads("other") == {}
    h = heads_mod.load_heads("M/1")["category"]
    emb = np.array([[1, 0, 0, 0]], dtype=np.float32)
    zs = np.array([[0.2, 0.3, 0.5]])
    p = h.blend(emb, zs, ["c", "b", "a"])  # порядок zero-shot отличается от порядка головы
    assert p.shape == (1, 3) and abs(p.sum() - 1) < 1e-6
    assert p[0, 2] > 0.6  # класс «a» из головы попал в свой столбец
    assert heads_mod.info()["trained"] is True


def test_lexicon_and_rank():
    assert lexicon_translate("двухъярусные кровати") == "bunk beds, beds"
    assert "swimming pool" in lexicon_translate("Бассейн")
    assert lexicon_translate("абракадабра") is None
    embs = np.array([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32)
    embs /= np.linalg.norm(embs, axis=1, keepdims=True)
    got = rank(np.array([1, 0], dtype=np.float32), ["x", "y", "z"], embs)
    assert [g[0] for g in got] == ["x", "y"]


def test_site_domain():
    assert site_domain("https://www.enu.kz/ru/") == "enu.kz"
    assert site_domain("nu.edu.kz") == "nu.edu.kz"
    assert site_domain("ЕНУ") is None and site_domain("Nazarbayev University") is None


def _photo(pid, boxes, sub=None):
    c = Candidate(source="commons", origin="category", page_url=f"https://c/{pid}", image_url=f"https://i/{pid}", download_url=f"https://i/{pid}")
    return Photo(candidate=c, retrieved="", width=500, height=400, category="dormitory", category_label="Общежития",
                 category_scores=[], confidence=0.9, level="high", signals=[], cluster=pid, shelfmark=f"ОБЩ-{pid}",
                 boxes=boxes, sub=sub or {"dorm_room": 0.9})


def test_bunk_fact():
    bed = lambda bunk: {"label": "кровать", "conf": 0.8, "x": 0, "y": 0, "w": 0.3, "h": 0.3, "bunk": bunk}  # noqa: E731
    photos = [_photo("1", [bed(0.9), bed(0.8)]), _photo("2", [bed(0.1)]), _photo("3", [bed(0.95)])]
    facts = {f.id: f for f in dorm_facts(photos, osm.Campus())}
    assert facts["dorm_bunk"].value == "есть на 2 из 3 фото"
    assert facts["dorm_bunk"].status == "confirmed"
    none = {f.id: f for f in dorm_facts([_photo("4", [bed(0.1)]), _photo("5", [bed(0.2)])], osm.Campus())}
    assert none["dorm_bunk"].value == "не видно на 2 фото"
    no_info = {f.id for f in dorm_facts([_photo("6", [{"label": "кровать", "conf": 0.8, "x": 0, "y": 0, "w": 1, "h": 1}])], osm.Campus())}
    assert "dorm_bunk" not in no_info


def test_compact_keeps_parse_result():
    full = osm.parse(fx.OVERPASS, enu())
    small = osm.parse(osm.compact(fx.OVERPASS), enu())
    assert small.rings == full.rings or len(small.rings) == len(full.rings)
    assert [o.kind for o in small.objects] == [o.kind for o in full.objects]


async def test_seed_cache_used_when_server_cache_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "seed_cache_dir", str(tmp_path / "seed"))
    cache.put("osm", fx.QID, osm.compact(fx.OVERPASS), target=cache.seed_path("osm", fx.QID))
    campus = await osm.fetch_campus(enu(), wait_s=0.01)
    assert campus.from_cache and campus.rings
