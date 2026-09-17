"""Замер скорости сборки профиля на живом сервисе: сценарий жюри, 10 запросов.

Замеряются три числа на каждый запрос:
* `first_photo` - когда в интерфейсе появилось первое проверенное фото;
* `ready` - когда профиль стал полезен (все источники разобраны, фото разложены по разделам);
* `total` - когда доехали факты, карта, климат и описание.

python ml/benchmark.py                       # локальный сервис на 8000
python ml/benchmark.py --base https://...    # развёрнутый сервис
python ml/benchmark.py --repeat 2 --cached   # ещё и повтор из общего кэша
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ml/BENCHMARK.md"

# Сценарий жюри: аббревиатуры, опечатка, адрес сайта, региональный вуз, зарубежный, несуществующий.
QUERIES = [
    "ЕНУ",
    "КазНУ",
    "Nazarbayev University",
    "КБТУ",
    "Satbayev University",
    "Astana IT University",
    "казахский национальный универистет",  # опечатка
    "kimep.kz",                            # адрес сайта
    "Университет Центральной Азии",
    "Ташкентский государственный университет",
]


def stream_profile(client: httpx.Client, base: str, qid: str, fresh: bool) -> dict:
    url = f"{base}/api/profile/{qid}/stream" + ("?fresh=1" if fresh else "")
    t0 = time.perf_counter()
    marks: dict[str, float] = {}
    counts = {"photos": 0, "rejected": 0, "categories": 0}
    event = ""
    with client.stream("GET", url, timeout=90) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
                continue
            if not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            now = time.perf_counter() - t0
            if event == "photos":
                counts["photos"] += len(data.get("photos", []))
                marks.setdefault("first_photo", now)
            elif event == "rejected":
                counts["rejected"] += len(data.get("items", []))
            elif event == "ready":
                marks["ready"] = now
                counts["categories"] = data.get("categories", 0)
            elif event == "meta" and data.get("replay"):
                marks["replay"] = now
            elif event == "facts":
                marks["facts"] = now
            elif event == "done":
                marks["total"] = now
                break
    return {"marks": marks, "counts": counts}


def run(base: str, repeat: int, cached: bool) -> list[dict]:
    rows: list[dict] = []
    with httpx.Client(follow_redirects=True) as client:
        for q in QUERIES:
            t0 = time.perf_counter()
            try:
                found = client.get(f"{base}/api/search", params={"q": q}, timeout=30).json()
            except httpx.HTTPError as e:
                rows.append({"query": q, "error": f"поиск не ответил: {type(e).__name__}"})
                continue
            search_ms = (time.perf_counter() - t0) * 1000
            if not found.get("candidates"):
                rows.append({"query": q, "search_ms": round(search_ms), "error": "вуз не найден"})
                continue
            qid = found["candidates"][0]["qid"]
            best: dict | None = None
            for attempt in range(repeat):
                try:
                    res = stream_profile(client, base, qid, fresh=attempt == 0)
                except httpx.HTTPError as e:
                    rows.append({"query": q, "qid": qid, "error": f"сборка не ответила: {type(e).__name__}"})
                    best = None
                    break
                if attempt == 0:
                    best = res
                elif cached:
                    best = {**(best or {}), "cached_s": res["marks"].get("total")}
            if best is None:
                continue
            m = best["marks"]
            rows.append({
                "query": q, "qid": qid, "label": found["candidates"][0].get("label", ""),
                "search_ms": round(search_ms),
                "first_photo_s": round(m.get("first_photo", 0), 1),
                "ready_s": round(m.get("ready", m.get("total", 0)), 1),
                "total_s": round(m.get("total", 0), 1),
                "cached_s": round(best.get("cached_s") or 0, 2) if best.get("cached_s") else None,
                **best["counts"],
            })
            print(json.dumps(rows[-1], ensure_ascii=False))
    return rows


def report(rows: list[dict], base: str) -> str:
    ok = [r for r in rows if "error" not in r]
    lines = [
        "# Скорость сборки профиля",
        "",
        f"Замер: `python ml/benchmark.py --base {base}`, {time.strftime('%Y-%m-%d %H:%M')}.",
        "Первый запрос каждого вуза идёт без кэша профиля.",
        "",
        "| Запрос | Вуз | Поиск, мс | Первое фото, с | Готово, с | Полностью, с | Фото | Отклонено |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['query']} | — | — | — | — | — | — | {r['error']} |")
            continue
        lines.append(f"| {r['query']} | {r['label']} | {r['search_ms']} | {r['first_photo_s']} | "
                     f"{r['ready_s']} | {r['total_s']} | {r['photos']} | {r['rejected']} |")
    if ok:
        lines += [
            "",
            f"**Медиана: первое фото {statistics.median(r['first_photo_s'] for r in ok):.1f} с, "
            f"профиль готов {statistics.median(r['ready_s'] for r in ok):.1f} с, "
            f"полностью {statistics.median(r['total_s'] for r in ok):.1f} с.**",
        ]
        cached = [r["cached_s"] for r in ok if r.get("cached_s")]
        if cached:
            lines.append(f"Повторное открытие из общего кэша: медиана {statistics.median(cached):.2f} с.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--repeat", type=int, default=1, help="сколько раз собирать каждый профиль")
    ap.add_argument("--cached", action="store_true", help="замерить повтор из кэша")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    rows = run(args.base.rstrip("/"), max(1, args.repeat), args.cached)
    text = report(rows, args.base)
    Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
