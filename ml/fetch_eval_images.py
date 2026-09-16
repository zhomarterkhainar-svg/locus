"""Скачивает фото проверочного набора с Wikimedia Commons по названиям файлов из index.json.

Фото не хранятся в репозитории: у каждого своя свободная лицензия и автор на странице файла.
python ml/fetch_eval_images.py
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "backend/tests/eval_images"
UA = "CandidAI-eval/0.1 (+https://github.com/zhomarterkhainar-svg/locus)"


def main() -> None:
    rows = json.loads((FOLDER / "index.json").read_text(encoding="utf-8"))
    for r in rows:
        target = FOLDER / r["file"]
        if target.exists() or not r["title"].startswith("File:"):
            continue
        name = urllib.parse.quote(r["title"].removeprefix("File:"))
        url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width=330"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        target.write_bytes(urllib.request.urlopen(req, timeout=20).read())
        print("ok", r["title"])
        time.sleep(0.5)


if __name__ == "__main__":
    main()
