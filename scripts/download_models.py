"""Скачивает веса моделей в папку models/.

Используются только публичные релизы на GitHub:
- OpenCLIP ViT-B-32 (LAION-400M), MIT: github.com/mlfoundations/open_clip
- Ultralytics YOLO11s (COCO), AGPL-3.0: github.com/ultralytics/assets
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "vit_b_32-quickgelu-laion400m_e32.pt": "https://github.com/mlfoundations/open_clip/releases/download/v0.2-weights/vit_b_32-quickgelu-laion400m_e32-46683a32.pt",
    "yolo11s.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s.pt",
}


def main() -> int:
    target = ROOT / "models"
    target.mkdir(exist_ok=True)
    for name, url in MODELS.items():
        path = target / name
        if path.exists() and path.stat().st_size > 1_000_000:
            print(f"ok   {name}")
            continue
        print(f"get  {name} <- {url}")
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        print(f"done {name} sha256:{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
