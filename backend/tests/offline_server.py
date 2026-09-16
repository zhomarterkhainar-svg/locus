"""Локальный сервер без интернета для e2e-проверки интерфейса и скриншотов.

Все внешние API подменены ответами реальной формы, фото берутся из tests/eval_images
(скачиваются ml/fetch_eval_images.py). Это инструмент разработки, не режим продукта.

cd backend && python tests/offline_server.py   ->   http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import respx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.responses import Response as FResponse  # noqa: E402
from httpx import Response  # noqa: E402

import api_fixtures as fx  # noqa: E402
from test_pipeline_offline import DORM, HOME, image_bytes  # noqa: E402

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}/_fixtures"
rows = json.loads((HERE / "eval_images/index.json").read_text(encoding="utf-8"))

CAMPUS_GEO = [(51.1575, 71.4660), (51.1580, 71.4690), (51.1568, 71.4705), (51.1590, 71.4645), (51.1560, 71.4680)]
FILES: dict[str, tuple[str, tuple[float, float] | None, str]] = {}
for i, r in enumerate(rows):
    label = r["label"]
    title = f"File:ENU {label} {i}.jpg" if not label.startswith("trash") else r["title"]
    if label == "city":
        geo = (51.128 + i * 0.001, 71.43 + i * 0.001)
        FILES[f"File:Astana street {i}.jpg"] = (r["file"], geo, "city")
        continue
    geo = CAMPUS_GEO[i % len(CAMPUS_GEO)] if label in ("dormitory", "sport", "canteen") else None
    FILES[title] = (r["file"], geo, "campus")


def commons_api(request):
    p = dict(request.url.params)
    if p.get("list") == "categorymembers":
        if "Eurasian" not in p["cmtitle"]:
            return Response(200, json={"query": {"categorymembers": []}})
        return Response(200, json={"query": {"categorymembers": [{"ns": 6, "title": t} for t, (_, g, s) in FILES.items() if g is None]}})
    if p.get("list") == "geosearch":
        lat = float(p["gscoord"].split("|")[0])
        scope = "campus" if abs(lat - 51.1602) < 0.001 else "city"
        return Response(200, json={"query": {"geosearch": [{"ns": 6, "title": t} for t, (_, g, s) in FILES.items() if g is not None and s == scope]}})
    if p.get("list") == "search":
        return Response(200, json={"query": {"search": []}})
    if p.get("prop", "").startswith("imageinfo"):
        pages = {}
        for i, t in enumerate(p["titles"].split("|")):
            if t not in FILES:
                continue
            fname, geo, scope = FILES[t]
            desc = "Евразийский национальный университет" if t.startswith("File:ENU") else ""
            cats = "L.N.Gumilyov Eurasian National University" if geo is None and t.startswith("File:ENU") else ""
            pages[str(i)] = fx.imageinfo_page(t, f"{BASE}/{fname}", *(geo or (None, None)), categories=cats, desc=desc)
        return Response(200, json={"query": {"pages": pages}})
    return Response(400)


def wikidata_api(request):
    p = dict(request.url.params)
    pool = {fx.QID: fx.ENU, "Q16250079": fx.OTHER, **fx.PLACES}
    if p.get("action") == "wbgetentities":
        return Response(200, json={"entities": {i: pool[i] for i in p["ids"].split("|") if i in pool}})
    if p.get("action") == "wbsearchentities":
        q = p.get("search", "").lower()
        hits = [{"id": fx.QID}] if any(w in q for w in ("евраз", "ену", "eurasian", "гумил")) else []
        return Response(200, json={"search": hits})
    if p.get("action") == "query":
        q = p.get("srsearch", "").lower()
        hits = [{"title": fx.QID}, {"title": "Q16250079"}] if any(w in q for w in ("евраз", "eurasian")) else []
        sug = {"suggestion": "Евразийский университет"} if "евроз" in q else {}
        return Response(200, json={"query": {"search": hits, "searchinfo": sug}})
    return Response(400)


def main() -> None:
    router = respx.mock(assert_all_called=False)
    router.start()
    router.route(host="127.0.0.1").pass_through()
    router.get("https://www.wikidata.org/w/api.php").mock(side_effect=wikidata_api)
    router.get("https://commons.wikimedia.org/w/api.php").mock(side_effect=commons_api)
    router.post(re.compile(r"https://overpass-api\.de/.*")).mock(return_value=Response(200, json=fx.OVERPASS))
    router.get(re.compile(r"https://ru\.wikipedia\.org/api/rest_v1/page/summary/.*")).mock(return_value=Response(200, json={
        "title": "Евразийский национальный университет",
        "extract": "Евразийский национальный университет имени Л. Н. Гумилёва — высшее учебное заведение в Астане. ЕНУ включает 13 факультетов и 28 научных учреждений. Подготовка ведётся по программам бакалавриата, магистратуры и докторантуры.",
        "content_urls": {"desktop": {"page": "https://ru.wikipedia.org/wiki/Евразийский_национальный_университет"}}}))
    router.get(re.compile(r"https://(en|kk)\.wikipedia\.org/.*")).mock(return_value=Response(404))
    router.get("https://enu.kz/robots.txt").mock(return_value=Response(404))
    router.get("https://enu.kz/").mock(return_value=Response(200, html=HOME))
    router.get("https://enu.kz/ru/page/dormitory").mock(return_value=Response(200, html=DORM.replace("https://upload.test/site/dormitory__Am.jpg", f"{BASE}/dormitory__hires_8.jpg")))
    router.get("https://enu.kz/ru/page/student-life").mock(return_value=Response(200, html="<html><title>Студенческая жизнь</title><body></body></html>"))

    from app.main import app

    @app.get("/_fixtures/{name}", include_in_schema=False)
    async def fixture(name: str):
        return FResponse(image_bytes(name), media_type="image/jpeg")

    # маршрут SPA зарегистрирован раньше, переносим фикстуры в начало
    app.router.routes.insert(0, app.router.routes.pop())

    async def local_image(request):
        name = request.url.path.rsplit("/", 1)[-1]
        return Response(200, content=image_bytes(name), headers={"content-type": "image/jpeg"})

    router.get(re.compile(rf"http://127\.0\.0\.1:{PORT}/_fixtures/.*")).mock(side_effect=local_image)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
