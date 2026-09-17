"""Заполняет backend/seed_cache сжатыми картами OSM для частых вузов (запускается в GitHub Actions).

python ml/seed_osm_cache.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ml"))

from app import cache, http  # noqa: E402
from app.main import PREWARM_QUERIES  # noqa: E402
from app.search import wikidata  # noqa: E402
from app.sources import osm  # noqa: E402
from benchmark import QUERIES  # noqa: E402
from build_calibrator_data import UNIVERSITIES  # noqa: E402

EXTRA = ["Astana Medical University", "Almaty University of Power Engineering and Telecommunications", "Kazakh-German University",
         "International IT University", "Narxoz University", "Al-Farabi Kazakh National University", "Maqsut Narikbayev University",
         "Kazakh National Agrarian Research University", "Karaganda Technical University", "Aktobe Regional University"]


async def main() -> None:
    bench = [q if isinstance(q, str) else q[0] for q in QUERIES]
    names = list(dict.fromkeys(PREWARM_QUERIES + bench + UNIVERSITIES + EXTRA))
    ok = 0
    print(f"вузов в списке: {len(names)}", flush=True)
    for name in names:
        try:
            res = await wikidata.search(name)
            if not res["candidates"]:
                print(f"пропуск {name}: Wikidata ничего не вернула ({res.get('status')})", flush=True)
                await asyncio.sleep(2)
                continue
            uni = await wikidata.get_university(res["candidates"][0]["qid"])
            if uni.lat is None:
                print(f"пропуск {name}: нет координат в Wikidata", flush=True)
                continue
            target = cache.seed_path("osm", uni.qid)
            if target.exists():
                ok += 1
                print(f"уже есть {uni.qid} {uni.label}", flush=True)
                continue
            t0 = time.time()
            data = await asyncio.wait_for(osm._load_raw(uni), timeout=240)
            cache.put("osm", uni.qid, data, target=target)
            ok += 1
            print(f"ok {uni.qid} {uni.label}: {len(data['elements'])} объектов за {time.time() - t0:.0f} с", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"пропуск {name}: {e!r}", flush=True)
        await asyncio.sleep(3)
    print(f"в seed-кэше {ok} вузов")
    await http.close()


if __name__ == "__main__":
    asyncio.run(main())
