"""Город и логистика: климат по месяцам (Open-Meteo), пешие и автомаршруты (OSRM на данных OSM),
инфраструктура рядом с кампусом (OSM). Всё из открытых источников, со ссылками; без данных честно пусто."""
from __future__ import annotations

import asyncio
import statistics
from datetime import date
from typing import Any

from .. import cache
from ..config import get_settings
from ..domain import University
from ..geo import Point, haversine
from ..http import SourceError, get_json
from .osm import Campus

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _years() -> tuple[int, int]:
    last = date.today().year - 1
    return last - 4, last


def aggregate_climate(daily: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Средние по месяцам из дневного архива: температура (средняя, мин, макс) и осадки за месяц."""
    times = daily.get("time", [])
    buckets: dict[int, dict[str, list[float]]] = {m: {"t": [], "lo": [], "hi": []} for m in range(1, 13)}
    precip: dict[tuple[int, int], float] = {}
    snow_days: dict[tuple[int, int], int] = {}
    for i, t in enumerate(times):
        y, m = int(t[:4]), int(t[5:7])
        for key, field in (("t", "temperature_2m_mean"), ("lo", "temperature_2m_min"), ("hi", "temperature_2m_max")):
            v = (daily.get(field) or [None] * len(times))[i]
            if v is not None:
                buckets[m][key].append(float(v))
        p = (daily.get("precipitation_sum") or [None] * len(times))[i]
        if p is not None:
            precip[(y, m)] = precip.get((y, m), 0.0) + float(p)
        sn = (daily.get("snowfall_sum") or [None] * len(times))[i]
        if sn is not None and float(sn) > 0.1:
            snow_days[(y, m)] = snow_days.get((y, m), 0) + 1
    out = []
    for m in range(1, 13):
        b = buckets[m]
        if not b["t"]:
            continue
        months_precip = [v for (yy, mm), v in precip.items() if mm == m]
        months_snow = [snow_days.get((yy, mm), 0) for (yy, mm) in precip if mm == m]
        out.append({
            "month": m,
            "label": MONTHS_RU[m - 1],
            "t_mean": round(statistics.fmean(b["t"]), 1),
            "t_min": round(statistics.fmean(b["lo"]), 1) if b["lo"] else None,
            "t_max": round(statistics.fmean(b["hi"]), 1) if b["hi"] else None,
            "precip_mm": round(statistics.fmean(months_precip)) if months_precip else None,
            "snow_days": round(statistics.fmean(months_snow)) if months_snow else None,
        })
    return out


async def climate(lat: float, lon: float) -> dict[str, Any]:
    s = get_settings()
    y0, y1 = _years()
    key = f"{lat:.2f},{lon:.2f},{y0}-{y1}"
    hit = cache.get("climate", key, s.context_cache_ttl_s)
    if hit is not None:
        return {**hit[0], "from_cache": True}
    params = {
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "start_date": f"{y0}-01-01", "end_date": f"{y1}-12-31",
        "daily": "temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum,snowfall_sum",
        "timezone": "auto",
    }
    data = await get_json(s.climate_url, params, timeout=s.context_timeout)
    months = aggregate_climate(data.get("daily", {}))
    if not months:
        raise SourceError("Open-Meteo вернул пустой архив")
    coldest = min(months, key=lambda m: m["t_mean"])
    warmest = max(months, key=lambda m: m["t_mean"])
    result = {
        "months": months, "years": f"{y0}–{y1}", "coldest": coldest, "warmest": warmest,
        "source": "Open-Meteo Historical Weather API (ERA5)",
        "url": f"https://open-meteo.com/en/docs/historical-weather-api#latitude={lat:.2f}&longitude={lon:.2f}",
    }
    cache.put("climate", key, result)
    return {**result, "from_cache": False}


async def route(a: Point, b: Point, mode: str) -> dict[str, Any] | None:
    """Маршрут OSRM (FOSSGIS, данные OSM). mode: foot | car."""
    s = get_settings()
    key = f"{mode}:{a[0]:.5f},{a[1]:.5f};{b[0]:.5f},{b[1]:.5f}"
    hit = cache.get("route", key, s.context_cache_ttl_s)
    if hit is not None:
        return hit[0]
    base = s.osrm_foot_url if mode == "foot" else s.osrm_car_url
    url = f"{base}/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}"
    data = await get_json(url, {"overview": "simplified", "geometries": "geojson", "steps": "false"}, timeout=s.context_timeout)
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    r = data["routes"][0]
    coords = r.get("geometry", {}).get("coordinates", [])
    result = {
        "distance_m": round(r["distance"]),
        "duration_s": round(r["duration"]),
        "line": [[round(lat, 5), round(lon, 5)] for lon, lat in coords][:400],
        "straight_m": round(haversine(a, b)),
        "source_url": f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_{'foot' if mode == 'foot' else 'car'}"
                      f"&route={a[0]:.5f}%2C{a[1]:.5f}%3B{b[0]:.5f}%2C{b[1]:.5f}",
    }
    cache.put("route", key, result)
    return result


def _main_point(uni: University, campus: Campus) -> Point | None:
    if uni.lat is not None:
        # Точка Wikidata обычно стоит на главном корпусе; если она вне границы, берём центр кампуса
        p = (uni.lat, uni.lon)
        if campus.rings and campus.distance(p) > 150 and campus.center:
            return campus.center
        return p
    return campus.center


def amenities_summary(campus: Campus, center: Point | None) -> dict[str, Any] | None:
    if center is None:
        return None
    counts: dict[str, int] = {"transport": 0, "shop": 0, "pharmacy": 0}
    nearest: dict[str, int] = {}
    for o in campus.objects:
        if o.kind not in counts:
            continue
        d = haversine(center, (o.lat, o.lon))
        if d <= 900:
            counts[o.kind] += 1
            nearest[o.kind] = min(nearest.get(o.kind, 10**9), round(d))
    if not any(counts.values()):
        return {"radius_m": 900, "counts": counts, "nearest_m": {}, "note": "OpenStreetMap не знает объектов рядом или карта не загрузилась."}
    return {"radius_m": 900, "counts": counts, "nearest_m": nearest}


async def build(uni: University, campus: Campus) -> dict[str, Any]:
    center = _main_point(uni, campus)
    out: dict[str, Any] = {"climate": None, "routes": [], "amenities": amenities_summary(campus, center),
                           "cost": {"status": "no_data", "note": "Открытых данных о стоимости жизни и цене общежития с понятной датой не нашлось."}}
    if center is None:
        out["error"] = "У вуза нет координат, климат и маршруты не посчитаны."
        return out

    jobs: dict[str, Any] = {"climate": climate(center[0], center[1])}
    city = uni.city
    if city and city.lat is not None and haversine(center, (city.lat, city.lon)) > 400:
        jobs["city_car"] = route((city.lat, city.lon), center, "car")
        jobs["city_foot"] = route((city.lat, city.lon), center, "foot")
    dorms = sorted((o for o in campus.objects if o.kind == "dormitory"), key=lambda o: haversine(center, (o.lat, o.lon)))
    for i, d in enumerate(dorms[:3]):
        if haversine(center, (d.lat, d.lon)) > 60:
            jobs[f"dorm_{i}"] = route((d.lat, d.lon), center, "foot")
    results = dict(zip(jobs, await asyncio.gather(*jobs.values(), return_exceptions=True)))

    clim = results.get("climate")
    out["climate"] = None if isinstance(clim, BaseException) else clim
    if isinstance(clim, BaseException):
        out["climate_error"] = str(clim) or "Open-Meteo не ответил"

    city_label = city.label if city else "центр города"
    for mode in ("car", "foot"):
        r = results.get(f"city_{mode}")
        if r and not isinstance(r, BaseException):
            out["routes"].append({"key": f"city_{mode}", "mode": mode, "label": f"От центра города ({city_label})",
                                  "from": {"name": city_label, "lat": city.lat, "lon": city.lon},
                                  "to": {"name": "главный корпус", "lat": center[0], "lon": center[1]}, **r})
    for i, d in enumerate(dorms[:3]):
        r = results.get(f"dorm_{i}")
        if r and not isinstance(r, BaseException):
            out["routes"].append({"key": f"dorm_{i}", "mode": "foot", "label": f"Пешком от общежития: {d.name or 'общежитие'}",
                                  "from": {"name": d.name or "общежитие", "lat": d.lat, "lon": d.lon, "osm_url": f"https://www.openstreetmap.org/{d.osm}"},
                                  "to": {"name": "главный корпус", "lat": center[0], "lon": center[1]}, **r})
    if out["climate"]:
        jan = out["climate"]["coldest"]
        dorm_routes = [r for r in out["routes"] if r["key"].startswith("dorm_")]
        if dorm_routes and jan["t_mean"] < 0:
            r = min(dorm_routes, key=lambda r: r["duration_s"])
            out["winter_walk"] = {"minutes": max(1, round(r["duration_s"] / 60)), "month": jan["label"], "t_mean": jan["t_mean"]}
    out["main_point"] = {"lat": center[0], "lon": center[1]}
    return out
