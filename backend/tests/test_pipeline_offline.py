"""Сквозная проверка сборки профиля без сети: все внешние API подменены ответами реальной формы."""
import io
import json
import re
from pathlib import Path

import pytest
import respx
from httpx import Response
from PIL import Image

import api_fixtures as fx
from app.pipeline.events import EventLog
from app.pipeline.orchestrator import ProfileBuild

IMAGES = Path(__file__).parent / "eval_images"
pytestmark = pytest.mark.skipif(not (IMAGES / "dormitory__commons_dorm1.jpg").exists(), reason="нет проверочных фото: python ml/fetch_eval_images.py")

FILES = {
    "File:Enu kampusy.JPG": ("campus__commons_campus.jpg", None),
    "File:Enu kampusy copy.jpg": ("campus__commons_campus.jpg", None),  # тот же кадр под другим именем
    "File:Dorm room ENU.jpg": ("dormitory__commons_dorm1.jpg", (51.1561, 71.4651)),
    "File:Dorm room 2 ENU.jpg": ("dormitory__hires_4.jpg", (51.1562, 71.4652)),
    "File:Dorm room 3 ENU.jpg": ("dormitory__hires_9.jpg", (51.1563, 71.4650)),
    "File:Dorm kitchen ENU.jpg": ("dormitory__commons_kitchen.jpg", (51.1561, 71.4652)),
    "File:ENU reading room.jpg": ("library__commons_library.jpg", None),
    "File:Stamps of Kazakhstan, 2012-34.jpg": ("trash_stamp__commons_stamp.jpg", None),
    "File:Far away pool.jpg": ("sport__File_Ribka_jpg.jpg", (51.40, 71.90)),
}


def image_bytes(name: str) -> bytes:
    im = Image.open(IMAGES / name).convert("RGB")
    if min(im.size) < 300:
        im = im.resize((im.width * 3, im.height * 3))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def commons_api(request):
    p = dict(request.url.params)
    if p.get("list") == "categorymembers":
        if "Eurasian" not in p["cmtitle"]:
            return Response(200, json={"query": {"categorymembers": []}})
        titles = [t for t, (_, geo) in FILES.items() if geo is None]
        return Response(200, json={"query": {"categorymembers": [{"ns": 6, "title": t} for t in titles]}})
    if p.get("list") == "geosearch":
        if abs(float(p["gscoord"].split("|")[0]) - 51.1602) < 0.001:
            titles = [t for t, (_, geo) in FILES.items() if geo is not None]
            return Response(200, json={"query": {"geosearch": [{"ns": 6, "title": t} for t in titles]}})
        return Response(200, json={"query": {"geosearch": []}})
    if p.get("list") == "search":
        return Response(200, json={"query": {"search": []}})
    if p.get("prop", "").startswith("imageinfo"):
        pages = {}
        for i, t in enumerate(p["titles"].split("|")):
            if t not in FILES:
                continue
            fname, geo = FILES[t]
            desc = "Евразийский национальный университет" if "ENU" in t else ""
            cats = "L.N.Gumilyov Eurasian National University" if geo is None else "Swimming pools"
            page = fx.imageinfo_page(t, f"https://upload.test/{i}/{fname}", *(geo or (None, None)), categories=cats, desc=desc)
            pages[str(i)] = page
        return Response(200, json={"query": {"pages": pages}})
    return Response(400)


HOME = """<html><head><title>ЕНУ</title><meta name="description" content="Евразийский национальный университет имени Л. Н. Гумилёва, Астана."></head>
<body><main><p>Евразийский национальный университет является одним из ведущих университетов Казахстана.
В кампусе расположены учебные корпуса, библиотека и общежития для студентов из разных регионов.</p>
<a href="/ru/page/dormitory">Общежития</a><a href="/ru/page/student-life">Студенческая жизнь</a>
<img src="/_nuxt/logo30t.svg"><img src="https://www.shutterstock.com/image-photo/students-campus-600w.jpg" width="600" height="400"></main></body></html>"""
DORM = """<html><head><title>Общежития ЕНУ</title></head><body><main><h1>Общежития</h1>
<img src="https://upload.test/site/dormitory__Am.jpg" alt="Комната в общежитии" width="800" height="600">
<img src="/icons/arrow.png" width="24" height="24"></main></body></html>"""


async def test_full_profile_offline():
    with respx.mock(assert_all_called=False) as r:
        def wd(request):
            ids = dict(request.url.params)["ids"].split("|")
            pool = {fx.QID: fx.ENU, **fx.PLACES}
            return Response(200, json={"entities": {i: pool[i] for i in ids if i in pool}})
        r.get("https://www.wikidata.org/w/api.php").mock(side_effect=wd)
        r.get("https://commons.wikimedia.org/w/api.php").mock(side_effect=commons_api)
        r.post(re.compile(r"https://overpass-api\.de/.*")).mock(return_value=Response(200, json=fx.OVERPASS))
        r.post(re.compile(r"https://.*/interpreter")).mock(return_value=Response(504))
        r.get(re.compile(r"https://archive-api\.open-meteo\.com/.*")).mock(return_value=Response(200, json={"daily": {
            "time": ["2024-01-01", "2024-07-01"], "temperature_2m_mean": [-14.0, 21.0], "temperature_2m_min": [-19.0, 14.0],
            "temperature_2m_max": [-9.0, 27.0], "precipitation_sum": [1.0, 2.0], "snowfall_sum": [1.0, 0.0]}}))
        r.get(re.compile(r"https://routing\.openstreetmap\.de/.*")).mock(return_value=Response(200, json={
            "code": "Ok", "routes": [{"distance": 900.0, "duration": 700.0, "geometry": {"coordinates": [[71.465, 51.156], [71.4648, 51.1602]]}}]}))
        r.get(re.compile(r"https://ru\.wikipedia\.org/api/rest_v1/page/summary/.*")).mock(return_value=Response(200, json={
            "title": "Евразийский национальный университет", "extract": "Евразийский национальный университет имени Л. Н. Гумилёва — высшее учебное заведение в Астане. ЕНУ включает 13 факультетов.",
            "content_urls": {"desktop": {"page": "https://ru.wikipedia.org/wiki/ЕНУ"}}}))
        r.get(re.compile(r"https://en\.wikipedia\.org/.*")).mock(return_value=Response(404))
        r.get("https://enu.kz/robots.txt").mock(return_value=Response(404))
        r.get("https://enu.kz/").mock(return_value=Response(200, html=HOME))
        r.get("https://enu.kz/ru/page/dormitory").mock(return_value=Response(200, html=DORM))
        r.get("https://enu.kz/ru/page/student-life").mock(return_value=Response(200, html="<html><title>Жизнь</title><body>пусто</body></html>"))

        def upload(request):
            name = request.url.path.rsplit("/", 1)[-1]
            if name == "dormitory__Am.jpg":
                # Кадр комнаты общежития, на котором видно кровать: на нём проверяется подсчёт фактов.
                name = "dormitory__File_Amasloĝejo_en_Ĉajanda_minejo_01_jpg.jpg"
            return Response(200, content=image_bytes(name), headers={"content-type": "image/jpeg"})
        r.get(re.compile(r"https://upload\.test/.*")).mock(side_effect=upload)

        log = EventLog(key=fx.QID)
        await ProfileBuild(fx.QID, log).run()

    events = [(e.type, e.data) for e in log.events]
    types = [t for t, _ in events]
    assert "university" in types and types[-1] == "done"
    assert "error" not in types, [d for t, d in events if t == "error"]
    photos = {}
    for t, d in events:
        if t == "photos":
            for p in d["photos"]:
                photos[p["id"]] = p
        if t == "photo_update":
            photos.pop(d["replaces"], None)
            photos[d["photo"]["id"]] = d["photo"]
    rejected = [i for t, d in events if t == "rejected" for i in d["items"]]
    reasons = {i["reason"] for i in rejected}
    cats = {p["category"] for p in photos.values()}

    assert "stock" in reasons, "фотобанк должен быть отклонён"
    assert "duplicate" in reasons, "копия кадра под другим именем должна склеиться"
    assert "trash" in reasons, "почтовая марка должна уйти в мусор"
    assert "far" in reasons, "бассейн в 30 км без названия вуза должен быть отклонён"
    assert "dormitory" in cats and "library" in cats
    dorm_geo = [p for p in photos.values() if p["title"].startswith("Dorm room ENU")]
    assert dorm_geo and dorm_geo[0]["level"] in ("high", "medium")
    assert dorm_geo[0]["nearest"] and dorm_geo[0]["nearest"]["kind"] == "dormitory"
    assert all(p["shelfmark"] for p in photos.values())

    facts = next(d for t, d in events if t == "facts")["facts"]
    by_id = {f["id"]: f for f in facts}
    assert by_id["dorm_osm"]["status"] == "confirmed"
    assert by_id["dorm_beds"]["status"] in ("weak", "confirmed"), by_id["dorm_beds"]
    desc = next(d for t, d in events if t == "description")
    assert desc["sentences"] and desc["mode"] in ("extractive", "gemini")
    assert all("—" not in s["text"] for s in desc["sentences"])
    ctx = next(d for t, d in events if t == "context")
    assert ctx["climate"]["coldest"]["t_mean"] == -14.0 and ctx["routes"]
    campus = next(d for t, d in events if t == "campus")
    assert campus["rings"]
    done = next(d for t, d in events if t == "done")
    assert done["total_ms"] < 30000
    print(json.dumps({"photos": len(photos), "rejected": sorted(reasons), "facts": {k: (v["value"], v["status"]) for k, v in by_id.items()}, "ms": done["total_ms"]}, ensure_ascii=False))
