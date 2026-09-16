"""Прогон сервиса на наборе вузов без кэша: время до первого фото и до готового профиля, счётчики,
статусы источников. Пишет ml/BENCHMARK.md и data/benchmark_sheet.html — лист для ручной проверки
precision@15 (открыть в браузере, отметить неверные фото).

Время замеряется на той машине, где запущен скрипт (в CI это 4 vCPU GitHub Actions; на HF Spaces 2 vCPU).

python ml/benchmark.py
"""
from __future__ import annotations

import asyncio
import html
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import http  # noqa: E402
from app.pipeline.events import EventLog  # noqa: E402
from app.pipeline.orchestrator import ProfileBuild  # noqa: E402
from app.search import wikidata  # noqa: E402

QUERIES = [
    ("ЕНУ", "крупный вуз Казахстана, аббревиатура"),
    ("КазНУ", "крупный вуз Казахстана, аббревиатура"),
    ("Nazarbayev Univercity", "крупный вуз Казахстана, опечатка"),
    ("KIMEP", "вуз Казахстана"),
    ("Торайгыров университет", "региональный вуз"),
    ("Kostanay Regional University", "маленький региональный вуз"),
    ("Technical University of Munich", "зарубежный"),
    ("МФТИ", "Россия, аббревиатура"),
    ("American University of Central Asia", "Центральная Азия"),
    ("Университет Хогвартс", "несуществующий"),
]


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


async def one(query: str) -> dict:
    t0 = time.perf_counter()
    res = await wikidata.search(query)
    t_search = time.perf_counter() - t0
    out = {"query": query, "status": res["status"], "search_s": round(t_search, 2), "candidates": [c["label"] for c in res["candidates"][:3]]}
    if not res["candidates"]:
        return out
    qid = res["candidates"][0]["qid"]
    log = EventLog(key=qid)
    t1 = time.perf_counter()
    await ProfileBuild(qid, log).run()
    total = time.perf_counter() - t1
    first_photo = next((e.t for e in log.events if e.type == "photos"), None)
    photos: dict[str, dict] = {}
    for e in log.events:
        if e.type == "photos":
            for p in e.data["photos"]:
                photos[p["id"]] = p
        elif e.type == "photo_update":
            photos.pop(e.data["replaces"], None)
            photos[e.data["photo"]["id"]] = e.data["photo"]
    confirmed = sorted((p for p in photos.values() if p["level"] != "low"), key=lambda p: -p["confidence"])
    sources = {e.data["key"]: e.data.get("status") for e in log.events if e.type == "source"}
    progress = [e.data for e in log.events if e.type == "progress"]
    facts = next((e.data["facts"] for e in log.events if e.type == "facts"), [])
    out.update({
        "qid": qid, "label": res["candidates"][0]["label"], "first_photo_s": None if first_photo is None else round(first_photo / 1000, 2),
        "total_s": round(total, 2), "confirmed": len(confirmed), "unconfirmed": sum(1 for p in photos.values() if p["level"] == "low"),
        "rejected": progress[-1]["rejected"] if progress else 0, "duplicates": progress[-1]["duplicates"] if progress else 0,
        "by_category": {k: sum(1 for p in confirmed if p["category"] == k) for k in sorted({p["category"] for p in confirmed})},
        "sources": sources, "facts_confirmed": sum(1 for f in facts if f["status"] == "confirmed"),
        "top15": [{"id": p["id"], "image": p["image_url"], "page": p["page_url"], "category": p["category_label"],
                   "confidence": p["confidence"], "title": p["title"]} for p in confirmed[:15]],
    })
    return out


def sheet(results: list[dict]) -> str:
    parts = ["<!doctype html><meta charset=utf-8><title>Candid AI: проверка precision@15</title>",
             "<style>body{font:14px system-ui;margin:24px}figure{display:inline-block;width:220px;margin:6px;vertical-align:top}"
             "img{width:220px;height:160px;object-fit:cover}label{display:block}</style>",
             "<h1>Проверка precision@15</h1><p>Отметьте фото, которое не относится к вузу или стоит не в том разделе. "
             "Итог считается внизу страницы.</p>"]
    for r in results:
        if not r.get("top15"):
            continue
        parts.append(f"<h2>{html.escape(r['label'])} ({r['qid']})</h2>")
        for p in r["top15"]:
            parts.append(f"<figure><a href='{html.escape(p['page'])}' target=_blank><img src='{html.escape(p['image'])}' loading=lazy></a>"
                         f"<figcaption>{html.escape(p['category'])} · {p['confidence']:.0%}<label><input type=checkbox class=bad> неверно</label>"
                         f"<label><input type=checkbox class=badcat> не тот раздел</label></figcaption></figure>")
    parts.append("<p id=total></p><script>function t(){const n=document.querySelectorAll('figure').length;"
                 "const b=document.querySelectorAll('.bad:checked').length;const c=document.querySelectorAll('.badcat:checked').length;"
                 "document.getElementById('total').textContent=`Принадлежность: ${((n-b)/n*100).toFixed(1)}% · раздел: ${((n-b-c)/n*100).toFixed(1)}% (${n} фото)`}"
                 "document.addEventListener('change',t);t()</script>")
    return "\n".join(parts)


async def main() -> None:
    results = []
    for q, kind in QUERIES:
        try:
            r = await one(q)
        except Exception as e:  # noqa: BLE001
            r = {"query": q, "status": "error", "error": repr(e)}
        r["kind"] = kind
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "top15"}, ensure_ascii=False), flush=True)
    await http.close()
    built = [r for r in results if r.get("total_s") is not None]
    totals = [r["total_s"] for r in built]
    firsts = [r["first_photo_s"] for r in built if r.get("first_photo_s") is not None]
    lines = ["# Бенчмарк сборки профиля", "",
             f"Дата: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. Без кэша, последовательно, на машине CI.", ""]
    if totals:
        lines += [f"- До первого подтверждённого фото: медиана {statistics.median(firsts):.1f} с, p95 {pct(firsts, 0.95):.1f} с" if firsts else "- Первых фото нет",
                  f"- До готового профиля: медиана {statistics.median(totals):.1f} с, p95 {pct(totals, 0.95):.1f} с", ""]
    lines += ["| Запрос | Тип | Результат поиска | Первое фото, с | Готово, с | Фото в фонде | Не подтв. | Изъято | Дубли | Факты ✓ |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['query']} | {r['kind']} | {r['status']}: {', '.join(r.get('candidates', [])[:1]) or '—'} | "
                     f"{r.get('first_photo_s', '—')} | {r.get('total_s', '—')} | {r.get('confirmed', '—')} | {r.get('unconfirmed', '—')} | "
                     f"{r.get('rejected', '—')} | {r.get('duplicates', '—')} | {r.get('facts_confirmed', '—')} |")
    lines += ["", "Точность precision@15 считается вручную по листу `data/benchmark_sheet.html` (артефакт CI) и вносится в README."]
    (ROOT / "ml" / "BENCHMARK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "benchmark_sheet.html").write_text(sheet(results), encoding="utf-8")
    (ROOT / "data" / "benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
