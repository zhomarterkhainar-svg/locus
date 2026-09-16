"""Фикстуры в форме реальных ответов API (сокращённые копии ответов для ЕНУ им. Гумилёва, сентябрь 2026)."""
from __future__ import annotations

QID = "Q127745"


def claim(prop, value, dtype="wikibase-item"):
    if dtype == "wikibase-item":
        dv = {"value": {"entity-type": "item", "id": value}, "type": "wikibase-entityid"}
    elif dtype == "coord":
        dv = {"value": {"latitude": value[0], "longitude": value[1]}, "type": "globecoordinate"}
    elif dtype == "time":
        dv = {"value": {"time": value, "precision": 9}, "type": "time"}
    elif dtype == "quantity":
        dv = {"value": {"amount": value, "unit": "1"}, "type": "quantity"}
    else:
        dv = {"value": value, "type": "string"}
    return {"mainsnak": {"snaktype": "value", "property": prop, "datavalue": dv}, "rank": "normal"}


ENU = {
    "id": QID,
    "labels": {
        "en": {"language": "en", "value": "L. N. Gumilyov Eurasian National University"},
        "kk": {"language": "kk", "value": "Еуразия ұлттық университеті"},
        "ru": {"language": "ru", "value": "Евразийский национальный университет имени Л. Н. Гумилёва"},
    },
    "descriptions": {"en": {"language": "en", "value": "university in Kazakhstan"}},
    "aliases": {"ru": [{"language": "ru", "value": "Евразийский национальный университет"}],
                "en": [{"language": "en", "value": "Eurasian National University"}]},
    "sitelinks": {"ruwiki": {"site": "ruwiki", "title": "Евразийский национальный университет"},
                  "enwiki": {"site": "enwiki", "title": "L. N. Gumilev Eurasian National University"}},
    "claims": {
        "P31": [claim("P31", "Q3918")],
        "P17": [claim("P17", "Q232")],
        "P131": [claim("P131", "Q1520")],
        "P625": [claim("P625", (51.1602, 71.4648), "coord")],
        "P856": [claim("P856", "https://enu.kz/", "string")],
        "P18": [claim("P18", "L.N.Gumilyov Eurasian National University.JPG", "string")],
        "P373": [claim("P373", "L.N.Gumilyov Eurasian National University", "string")],
        "P571": [claim("P571", "+1996-00-00T00:00:00Z", "time")],
        "P2196": [claim("P2196", "+11300", "quantity")],
    },
}
OTHER = {
    "id": "Q16250079",
    "labels": {"ru": {"language": "ru", "value": "Инновационный евразийский университет"},
               "en": {"language": "en", "value": "Innovative University of Eurasia"}},
    "descriptions": {"ru": {"language": "ru", "value": "университет в городе Павлодаре (Казахстан)"}},
    "aliases": {}, "sitelinks": {},
    "claims": {"P31": [claim("P31", "Q3918")], "P17": [claim("P17", "Q232")]},
}
SINGER = {
    "id": "Q29994676", "labels": {"ru": {"language": "ru", "value": "Ёну"}},
    "descriptions": {"en": {"language": "en", "value": "South Korean pop singer turned actress"}},
    "aliases": {}, "sitelinks": {}, "claims": {"P31": [claim("P31", "Q5")]},
}
PLACES = {
    "Q232": {"id": "Q232", "labels": {"ru": {"language": "ru", "value": "Казахстан"}}, "claims": {}},
    "Q1520": {"id": "Q1520", "labels": {"ru": {"language": "ru", "value": "Астана"}},
              "claims": {"P625": [claim("P625", (51.1333, 71.4333), "coord")]}},
}


def campus_way(points):
    return [{"lat": a, "lon": b} for a, b in points]


OVERPASS = {"elements": [
    {"type": "relation", "id": 13009591, "tags": {"amenity": "university", "wikidata": QID, "name:ru": "ЕНУ"},
     "members": [
         {"type": "way", "role": "outer", "geometry": campus_way([(51.1603, 71.4627), (51.1600, 71.4730), (51.1550, 71.4730)])},
         {"type": "way", "role": "outer", "geometry": campus_way([(51.1550, 71.4730), (51.1550, 71.4627), (51.1603, 71.4627)])},
     ]},
    {"type": "way", "id": 44127708, "center": {"lat": 51.1565, "lon": 71.4714},
     "tags": {"amenity": "university", "building": "yes", "name:ru": "Учебный корпус №3"}},
    {"type": "node", "id": 4242718989, "lat": 51.1530, "lon": 71.4800,
     "tags": {"amenity": "university", "name:ru": "Казахстанский филиал МГУ"}},
    {"type": "way", "id": 1, "center": {"lat": 51.1560, "lon": 71.4650}, "tags": {"building": "dormitory", "name": "Общежитие №1"}},
    {"type": "way", "id": 2, "center": {"lat": 51.1580, "lon": 71.4700}, "tags": {"leisure": "swimming_pool", "name": "Бассейн"}},
    {"type": "node", "id": 3, "lat": 51.1602909, "lon": 71.465432, "tags": {"amenity": "library", "name:ru": "Читальный зал ЕНУ"}},
]}


def imageinfo_page(title, url, lat=None, lon=None, categories="L.N.Gumilyov Eurasian National University", desc=""):
    page = {
        "title": title,
        "imageinfo": [{
            "timestamp": "2013-03-18T05:37:24Z", "width": 2000, "height": 1300, "mime": "image/jpeg",
            "thumburl": url, "url": url, "descriptionurl": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
            "extmetadata": {
                "ImageDescription": {"value": desc},
                "DateTimeOriginal": {"value": "2013-03-18 11:49:26"},
                "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Test">Test</a>'},
                "LicenseShortName": {"value": "CC BY-SA 3.0"},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/3.0"},
                "Categories": {"value": categories},
            },
        }],
    }
    if lat is not None:
        page["coordinates"] = [{"lat": lat, "lon": lon}]
    return page
