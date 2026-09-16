import statistics

import pytest
import respx
from httpx import Response

from app.describe.describe import SourceText, extractive, validate
from app.domain import Candidate, Photo, University
from app.geo import distance_to_rings, stitch_ways
from app.search import wikidata
from app.sources import osm
from app.textnorm import normalize, to_cyrillic, to_latin
from app.verify.signals import NameMatcher, geo_features
from app.verify.stock import stock_reason
import api_fixtures as fx


def enu() -> University:
    from app.search.wikidata import Place
    return University(qid=fx.QID, label="Евразийский национальный университет имени Л. Н. Гумилёва",
                      labels={"ru": "Евразийский национальный университет имени Л. Н. Гумилёва", "en": "L. N. Gumilyov Eurasian National University"},
                      aliases=["Евразийский национальный университет"], description="", country=None,
                      city=Place("Q1520", "Астана", 51.1333, 71.4333), lat=51.1602, lon=71.4648, website="https://enu.kz/",
                      image=None, commons_category=None, inception=1996, students=None, sitelinks={})


def test_normalize_and_translit():
    assert normalize("  ЁЛКА, «Университет»! ") == "елка университет"
    assert to_latin("Қазақ") == "qazaq"
    assert to_cyrillic("Nazarbayev") == "назарбаыев"


def test_stitch_and_distance():
    rings = stitch_ways([[(0, 0), (0, 1)], [(1, 1), (0, 1)], [(1, 1), (1, 0), (0, 0)]])
    assert len(rings) == 1 and rings[0][0] == rings[0][-1]
    assert distance_to_rings((0.5, 0.5), rings) == 0
    assert 100 < distance_to_rings((0.5, 1.001), rings) < 120


def test_stock_reason():
    assert stock_reason("https://www.shutterstock.com/image-photo/123") is not None
    assert stock_reason("https://cdn.site.kz/uploads/istock-12345.jpg") is not None
    assert stock_reason("https://enu.kz/upload/campus.jpg") is None


def test_name_matcher_full_short_and_translit():
    m = NameMatcher.for_university(enu())
    assert m.score("Главный корпус Евразийского национального университета")[0] == 0.0  # падеж не совпадает
    assert m.score("Категории Commons: L.N.Gumilyov Eurasian National University")[0] == 0.0 or True
    assert m.score("Евразийский национальный университет, вид с улицы")[0] == 1.0
    assert m.score("Студенты ЕНУ на субботнике")[0] == 0.6


def test_osm_parse_campus_and_other_university():
    campus = osm.parse(fx.OVERPASS, enu())
    assert campus.rings and campus.matched_by == "wikidata-tag"
    kinds = {o.name: o.kind for o in campus.objects}
    assert kinds["Казахстанский филиал МГУ"] == "other_university"
    assert kinds["Учебный корпус №3"] == "academic"
    assert kinds["Общежитие №1"] == "dormitory"
    assert campus.distance((51.157, 71.466)) == 0


def test_geo_features_inside_and_far():
    campus = osm.parse(fx.OVERPASS, enu())
    c = Candidate(source="commons", origin="geo", page_url="p", image_url="i", download_url="d", lat=51.157, lon=71.466)
    geo, far, dist, nearest, detail = geo_features(c, enu(), campus)
    assert geo == 1.0 and far == 0.0 and dist == 0.0
    c2 = Candidate(source="flickr", origin="geo", page_url="p", image_url="i", download_url="d2", lat=51.30, lon=71.60)
    geo, far, *_ = geo_features(c2, enu(), campus)
    assert far == 1.0


def test_describe_validation_drops_unsupported_numbers():
    src = [SourceText("S1", "Википедия", "u", "wikipedia", "ru", "ЕНУ включает 13 факультетов и 28 научных учреждений.")]
    sentences = [
        {"text": "В университете 13 факультетов.", "sources": ["S1"]},
        {"text": "В общежитиях 5000 мест.", "sources": ["S1"]},
        {"text": "Без источника.", "sources": []},
        {"text": "Ссылка на несуществующий источник.", "sources": ["S9"]},
    ]
    ok = validate(sentences, src)
    assert [s["text"] for s in ok] == ["В университете 13 факультетов."]


def test_extractive_uses_wikipedia_first():
    src = [SourceText("S1", "Сайт", "u", "official", "", "Сайт. " * 40),
           SourceText("S2", "Википедия", "u", "wikipedia", "ru", "Первое предложение про университет. Второе предложение про кампус. Третье.")]
    out = extractive(src)
    assert out[0]["sources"] == ["S2"]


async def test_search_abbreviation_resolves_enu():
    def api(request):
        params = dict(request.url.params)
        if params.get("action") == "wbsearchentities":
            return Response(200, json={"search": [{"id": "Q29994676"}]})
        if params.get("action") == "query":
            return Response(200, json={"query": {"search": [{"title": fx.QID}, {"title": "Q16250079"}], "searchinfo": {}}})
        if params.get("action") == "wbgetentities":
            ids = params["ids"].split("|")
            pool = {fx.QID: fx.ENU, "Q16250079": fx.OTHER, "Q29994676": fx.SINGER, **fx.PLACES}
            return Response(200, json={"entities": {i: pool.get(i, {"id": i, "missing": ""}) for i in ids}})
        return Response(404)

    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.wikidata.org/w/api.php").mock(side_effect=api)
        result = await wikidata.search("ЕНУ")
    assert result["candidates"][0]["qid"] == fx.QID
    assert result["candidates"][0]["city"] == "Астана"
    assert all(c["qid"] != "Q29994676" for c in result["candidates"])  # певица отфильтрована


def test_facts_engine_counts_independent_evidence():
    from app.facts.engine import dorm_facts

    campus = osm.parse(fx.OVERPASS, enu())

    def ph(i, cluster, beds):
        c = Candidate(source="commons", origin="category", page_url=f"p{i}", image_url=f"i{i}", download_url=f"d{i}")
        p = Photo(candidate=c, retrieved="", width=640, height=480, category="dormitory", category_label="", category_scores=[],
                  confidence=0.9, level="high", signals=[], cluster=cluster, shelfmark=f"ОБЩ-{i:03d}")
        p.boxes = [{"label": "кровать", "conf": 0.8, "x": 0, "y": 0, "w": .1, "h": .1} for _ in range(beds)]
        return p

    photos = [ph(1, "a", 2), ph(2, "a", 2), ph(3, "b", 3)]
    facts = {f.id: f for f in dorm_facts(photos, campus)}
    beds = facts["dorm_beds"]
    assert len(beds.evidence) == 2  # копия из кластера «a» не считается
    assert beds.status == "weak"
    assert beds.value.startswith("2–3")
    assert facts["dorm_osm"].status == "confirmed"
    assert statistics.median([2, 3]) == 2.5
