"""Считает эмбеддинги текстовых промптов заранее и кладёт их в ml/prompts/<модель>.json.

Зачем. В рабочем сервисе текстовый энкодер CLIP нужен только для поиска по фото своими словами.
Если эмбеддинги промптов категорий посчитаны заранее, сервису на старте достаточно картиночной
части модели: минус 60 МБ памяти и минус несколько секунд холодного старта. Файл проверяется по
хэшу набора промптов, поэтому после правки categories.py его надо пересчитать.

python ml/build_prompts.py            # модель из настроек
python ml/build_prompts.py --all      # все модели из onnx_backend.MODELS
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.vision import onnx_backend as ob  # noqa: E402
from app.vision.clip_model import ClipModel, prompts_hash, prompts_path  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true", help="пересчитать, даже если файл совпадает по хэшу")
    args = ap.parse_args()
    s = get_settings()
    keys = list(ob.MODELS) if args.all else [s.clip_model if s.clip_model in ob.MODELS else "clip_vitb32"]
    for key in keys:
        path = prompts_path(key)
        if args.force and path.exists():
            path.unlink()
        model = ClipModel(spec=ob.MODELS[key])
        print(f"{key}: {path.relative_to(ROOT)}, промпты {prompts_hash()}, размерность {model.dim}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
