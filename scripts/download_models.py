"""Скачивает веса моделей в каталог models/ (вызывается при сборке образа и локально).

Все веса открытые, в формате ONNX:
- CLIP ViT-B/32 (OpenAI), int8, экспорт Xenova: huggingface.co/Xenova/clip-vit-base-patch32
- MobileCLIP-S0 (Apple), запасная модель: huggingface.co/Xenova/mobileclip_s0
- YOLOv10-nano (COCO), AGPL-3.0: huggingface.co/onnx-community/yolov10n

python scripts/download_models.py            # модель по умолчанию + детектор
python scripts/download_models.py --all      # ещё и запасную модель CLIP
python scripts/download_models.py --text     # ещё и текстовый энкодер (нужен для поиска по фото
                                             # своими словами, если нет ml/prompts/*.json)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.vision import onnx_backend as ob  # noqa: E402


def mb(p: Path) -> str:
    return f"{p.stat().st_size / 1048576:.1f} МБ"


def main(argv: list[str]) -> int:
    want_all = "--all" in argv
    want_text = "--text" in argv or want_all
    s = get_settings()
    keys = list(ob.MODELS) if want_all else [s.clip_model if s.clip_model in ob.MODELS else "clip_vitb32"]
    d = ob.models_dir()
    for key in keys:
        spec = ob.MODELS[key]
        parts = ["vision"] + (["text", "tokenizer"] if want_text else [])
        for part in parts:
            target = d / ob.local_name(spec, part)
            p = ob.ensure_file(ob.HF.format(repo=spec.repo, file=ob.remote_file(spec, part)), target)
            print(f"ok {p.name} ({mb(p)}) <- {spec.repo}/{ob.remote_file(spec, part)}")
    det = d / ob.DETECTOR["local"]
    p = ob.ensure_file(ob.HF.format(repo=ob.DETECTOR["repo"], file=ob.DETECTOR["file"]), det)
    print(f"ok {p.name} ({mb(p)}) <- {ob.DETECTOR['repo']}/{ob.DETECTOR['file']}")
    print(f"\nвсе веса в {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
