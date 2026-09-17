"""Скачивает фото проверочного набора с Wikimedia Commons по названиям файлов из index.json.

Фото не хранятся в репозитории: у каждого своя свободная лицензия и автор на странице файла.
python ml/fetch_eval_images.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "backend/tests/eval_images"
UA = "CandidAI-eval/1.0 (+https://github.com/zhomarterkhainar-svg/locus)"


def say(*parts: object) -> None:
    """Печать без падения на консолях Windows с однобайтовой кодировкой."""
    line = " ".join(str(p) for p in parts)
    enc = sys.stdout.encoding or "utf-8"
    sys.stdout.write(line.encode(enc, "replace").decode(enc, "replace") + "\n")


def fetch(url: str, tries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:  # noqa: PERF203
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("не скачалось")


def main() -> int:
    rows = json.loads((FOLDER / "index.json").read_text(encoding="utf-8"))
    ok = skipped = failed = 0
    for r in rows:
        target = FOLDER / r["file"]
        if target.exists() and target.stat().st_size > 1024:
            skipped += 1
            continue
        if not r["title"].startswith("File:"):
            skipped += 1
            continue
        name = urllib.parse.quote(r["title"].removeprefix("File:").replace(" ", "_"))
        url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width=330"
        try:
            data = fetch(url)
        except Exception as e:  # noqa: BLE001  один недоступный файл не должен ронять весь набор
            failed += 1
            say("ПРОПУСК", r["title"], "-", type(e).__name__)
            continue
        target.write_bytes(data)
        ok += 1
        say("ok", r["title"])
        time.sleep(0.3)
    say(f"\nскачано {ok}, уже было {skipped}, не удалось {failed}, всего в наборе {len(rows)}")
    return 0 if ok + skipped >= len(rows) * 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
