"""ONNX Runtime вместо PyTorch: модели грузятся за секунды и живут в 512 МБ памяти.

Почему так. Для бесплатного хостинга (Render, 512 МБ RAM) стек torch + open_clip + ultralytics
не подходит: только веса занимают 600 МБ, а холодный старт идёт минуты. Те же модели в формате
ONNX весят 45 МБ, запускаются за 2 секунды и считаются на CPU в 2-4 раза быстрее. Веса берутся
из открытых репозиториев Hugging Face (см. MODELS), скачиваются при сборке образа скриптом
scripts/download_models.py и кэшируются в каталоге models/.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("candid.onnx")

HF = "https://huggingface.co/{repo}/resolve/main/{file}"


@dataclass(frozen=True)
class VisionSpec:
    """Как готовить картинку и где брать веса для конкретной модели CLIP."""

    key: str
    repo: str
    vision_file: str
    text_file: str
    tokenizer_file: str
    image_size: int
    mean: tuple[float, float, float] | None  # None - только деление на 255 (MobileCLIP)
    std: tuple[float, float, float] | None
    context_length: int = 77
    pad_token: int = 0  # MobileCLIP дополняет нулями, OpenAI CLIP - токеном конца текста
    resample: int = 3  # как в preprocessor_config.json модели: 3 - бикубическая, 2 - билинейная


MODELS: dict[str, VisionSpec] = {
    # Основная модель: CLIP ViT-B/32 (OpenAI) в int8, экспорт Xenova. На CPU считает кадр за
    # 15 мс на 4 потоках и 44 мс на одном - быстрее, чем MobileCLIP-S0 в ONNX Runtime
    # (его reparam-блоки на CPU считаются медленно, замеры в ml/BENCHMARK.md).
    "clip_vitb32": VisionSpec(
        key="clip_vitb32",
        repo="Xenova/clip-vit-base-patch32",
        vision_file="onnx/vision_model_quantized.onnx",
        text_file="onnx/text_model_quantized.onnx",
        tokenizer_file="tokenizer.json",
        image_size=224,
        mean=(0.48145466, 0.4578275, 0.40821073),
        std=(0.26862954, 0.26130258, 0.27577711),
        pad_token=49407,
    ),
    # Запасная: Apple MobileCLIP-S0 (экспорт Xenova), fp32, 43 МБ. Точнее на zero-shot,
    # но на ORT CPU медленнее; включается переменной CLIP_MODEL=mobileclip_s0.
    "mobileclip_s0": VisionSpec(
        key="mobileclip_s0",
        repo="Xenova/mobileclip_s0",
        vision_file="onnx/vision_model.onnx",
        text_file="onnx/text_model_quantized.onnx",
        tokenizer_file="tokenizer.json",
        image_size=256,
        mean=None,
        std=None,
        pad_token=0,
        resample=2,
    ),
}

# YOLOv10-s int8: 7,6 МБ, находит кровати и мебель заметно надёжнее nano-версии
# (замеры на проверочном наборе общежитий в ml/REPORT.md), считает кадр за ~150 мс на CPU.
DETECTOR = {
    "repo": "onnx-community/yolov10s",
    "file": "onnx/model_quantized.onnx",
    "local": "yolov10s.onnx",
}


def local_name(spec: VisionSpec, part: str) -> str:
    ext = {"vision": "_vision.onnx", "text": "_text.onnx", "tokenizer": "_tokenizer.json"}[part]
    return f"{spec.key}{ext}"


def remote_file(spec: VisionSpec, part: str) -> str:
    return {"vision": spec.vision_file, "text": spec.text_file, "tokenizer": spec.tokenizer_file}[part]


def models_dir() -> Path:
    from ..config import get_settings

    s = get_settings()
    d = s.path(s.models_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_file(url: str, target: Path, allow_download: bool = True) -> Path:
    """Возвращает путь к весам, при необходимости скачивая их один раз."""
    if target.exists() and target.stat().st_size > 1024:
        return target
    if not allow_download:
        raise FileNotFoundError(f"нет файла модели {target.name}: запустите python scripts/download_models.py")
    import httpx

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.part")
    log.info("скачиваю %s -> %s", url, target.name)
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(300.0, connect=20.0),
                      headers={"User-Agent": "candid-ai/1.0"}) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(target)
    return target


_session_lock = threading.Lock()


def session(path: Path, threads: int | None = None) -> Any:
    """InferenceSession с настройками под маленькую машину: без арены памяти, фиксированное число потоков."""
    import onnxruntime as ort

    from ..config import get_settings

    s = get_settings()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = int(threads or s.onnx_threads or (os.cpu_count() or 2))
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.enable_cpu_mem_arena = bool(s.onnx_mem_arena)
    opts.enable_mem_pattern = bool(s.onnx_mem_arena)
    opts.log_severity_level = 3
    with _session_lock:
        return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


@dataclass
class Tokenizer:
    """CLIP BPE из tokenizer.json (библиотека tokenizers), дополнение до context_length."""

    path: Path
    context_length: int
    pad_token: int
    _tok: Any = field(default=None, repr=False)

    def encode(self, texts: list[str]) -> Any:
        import numpy as np
        from tokenizers import Tokenizer as HFTokenizer

        if self._tok is None:
            self._tok = HFTokenizer.from_file(str(self.path))
            self._tok.no_truncation()
            self._tok.no_padding()
        out = np.full((len(texts), self.context_length), self.pad_token, dtype=np.int64)
        for i, enc in enumerate(self._tok.encode_batch([t.lower().strip() for t in texts])):
            ids = enc.ids[: self.context_length]
            out[i, : len(ids)] = ids
        return out
