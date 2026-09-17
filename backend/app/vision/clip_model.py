"""CLIP на ONNX Runtime: эмбеддинги изображений, zero-shot категории, поиск по тексту.

Модель по умолчанию - CLIP ViT-B/32 (OpenAI) в int8, экспорт Xenova: 15 мс на кадр на четырёх
потоках CPU против 60-80 мс у той же модели на PyTorch, что и позволяет держать сборку профиля
в пределах 10 секунд. Альтернатива MobileCLIP-S0 включается переменной CLIP_MODEL.
Текстовые промпты категорий не кодируются при каждом старте: их эмбеддинги посчитаны заранее
(ml/prompts/<модель>.json, скрипт ml/build_prompts.py), поэтому текстовый энкодер вообще не
загружается, пока пользователь не ищет по фото своими словами.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from ..config import get_settings
from . import onnx_backend as ob
from .categories import BUNK_PROMPTS, CATEGORIES, SUB_PROMPTS, TRASH, WATERMARK_PROMPTS
from .heads import Head, load_heads

log = logging.getLogger("candid.clip")
_lock = threading.Lock()  # общий: создание модели
_text_lock = threading.Lock()  # отдельный: ленивая загрузка текстового энкодера внутри __init__
_model: "ClipModel | None" = None


def prompt_groups() -> dict[str, list[list[str]]]:
    """Все наборы промптов сервиса в одном месте: по ним считается кэш текстовых эмбеддингов."""
    return {
        "class": [CATEGORIES[k][1] for k in CATEGORIES] + [TRASH[k][1] for k in TRASH],
        "watermark": [WATERMARK_PROMPTS],
        "sub": [SUB_PROMPTS[k] for k in SUB_PROMPTS],
        "bunk": [BUNK_PROMPTS[k] for k in BUNK_PROMPTS],
    }


def prompts_hash() -> str:
    return hashlib.sha1(json.dumps(prompt_groups(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def prompts_path(key: str) -> Path:
    s = get_settings()
    return s.path(s.prompts_dir) / f"{key}.json"


class ClipModel:
    def __init__(self, spec: ob.VisionSpec | None = None, allow_download: bool = True) -> None:
        s = get_settings()
        self.spec = spec or ob.MODELS.get(s.clip_model, ob.MODELS["clip_vitb32"])
        d = ob.models_dir()
        vision_path = ob.ensure_file(
            ob.HF.format(repo=self.spec.repo, file=self.spec.vision_file),
            d / ob.local_name(self.spec, "vision"), allow_download)
        self.vision = ob.session(vision_path)
        self.vision_input = self.vision.get_inputs()[0].name
        self.vision_output = self._pick_output(self.vision, ("image_embeds", "text_embeds"))
        self._text: Any = None
        self._tokenizer: ob.Tokenizer | None = None
        self._text_input: list[str] = []
        self._text_output = ""
        self.allow_download = allow_download

        self.model_id = f"{self.spec.repo}/{Path(self.spec.vision_file).name}"
        self.key = self.spec.key
        self.name = f"{self.spec.repo.split('/')[-1]} (ONNX)"
        self.heads: dict[str, Head] = load_heads(self.model_id)
        if self.heads:
            self.name += " + обученные головы (" + ", ".join(sorted(self.heads)) + ")"

        self.class_keys = list(CATEGORIES) + [f"trash:{k}" for k in TRASH]
        self.sub_keys = list(SUB_PROMPTS)
        self.bunk_keys = list(BUNK_PROMPTS)
        groups = self._prompt_embeddings()
        self.class_emb = groups["class"]
        self.watermark_emb = groups["watermark"][0]
        self.sub_emb = groups["sub"]
        self.bunk_emb = groups["bunk"]
        self.dim = int(self.class_emb.shape[1])

    # ---------- подготовка ----------

    @staticmethod
    def _pick_output(sess: Any, preferred: tuple[str, ...]) -> str:
        names = [o.name for o in sess.get_outputs()]
        for p in preferred:
            if p in names:
                return p
        return names[0]

    def _prompt_embeddings(self) -> dict[str, np.ndarray]:
        """Читает заранее посчитанные эмбеддинги промптов, иначе считает их и кладёт в кэш."""
        path = prompts_path(self.spec.key)
        want = prompts_hash()
        if path.exists():
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
                if blob.get("hash") == want and blob.get("model") == self.model_id:
                    return {k: np.asarray(v, dtype=np.float32) for k, v in blob["groups"].items()}
                log.info("кэш промптов устарел, пересчитываю")
            except (ValueError, KeyError) as e:
                log.warning("кэш промптов не прочитался: %s", e)
        groups = {k: np.stack([self._mean_text(p) for p in lists]) for k, lists in prompt_groups().items()}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "model": self.model_id, "hash": want, "dim": int(next(iter(groups.values())).shape[1]),
                "groups": {k: np.round(v, 6).tolist() for k, v in groups.items()},
            }, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            log.info("кэш промптов не сохранён: %s", e)
        return groups

    def _mean_text(self, prompts: list[str]) -> np.ndarray:
        t = self.embed_text(prompts)
        m = t.mean(axis=0)
        return (m / np.linalg.norm(m)).astype(np.float32)

    def _text_session(self) -> tuple[Any, ob.Tokenizer]:
        if self._text is None:
            with _text_lock:
                if self._text is None:
                    d = ob.models_dir()
                    text_path = ob.ensure_file(ob.HF.format(repo=self.spec.repo, file=self.spec.text_file),
                                               d / ob.local_name(self.spec, "text"), self.allow_download)
                    tok_path = ob.ensure_file(ob.HF.format(repo=self.spec.repo, file=self.spec.tokenizer_file),
                                              d / ob.local_name(self.spec, "tokenizer"), self.allow_download)
                    sess = ob.session(text_path)
                    self._text_input = [i.name for i in sess.get_inputs()]
                    self._text_output = self._pick_output(sess, ("text_embeds", "image_embeds"))
                    self._tokenizer = ob.Tokenizer(tok_path, self.spec.context_length, self.spec.pad_token)
                    self._text = sess
        return self._text, self._tokenizer  # type: ignore[return-value]

    # ---------- изображения ----------

    def preprocess(self, img: Image.Image) -> np.ndarray:
        n = self.spec.image_size
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        scale = n / min(w, h)
        # Resize по короткой стороне и центральный кроп ровно как в preprocessor_config.json модели:
        # у CLIP это бикубическая интерполяция, замена на билинейную заметно портит точность.
        rw, rh = max(n, round(w * scale)), max(n, round(h * scale))
        if (w, h) != (rw, rh):
            img = img.resize((rw, rh), Image.Resampling(self.spec.resample))
        left, top = (rw - n) // 2, (rh - n) // 2
        img = img.crop((left, top, left + n, top + n))
        a = np.asarray(img, dtype=np.float32) / 255.0
        if self.spec.mean is not None and self.spec.std is not None:
            a = (a - np.asarray(self.spec.mean, dtype=np.float32)) / np.asarray(self.spec.std, dtype=np.float32)
        return np.ascontiguousarray(a.transpose(2, 0, 1))

    def embed_images(self, images: list[Image.Image], batch: int = 16) -> np.ndarray:
        if not images:
            return np.zeros((0, getattr(self, "dim", 512)), dtype=np.float32)
        out = []
        for i in range(0, len(images), batch):
            arr = np.stack([self.preprocess(im) for im in images[i:i + batch]])
            e = self.vision.run([self.vision_output], {self.vision_input: arr})[0].astype(np.float32)
            out.append(e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-8))
        return np.concatenate(out)

    def embed_text(self, texts: list[str]) -> np.ndarray:
        sess, tok = self._text_session()
        ids = tok.encode(texts)
        feed: dict[str, Any] = {}
        for name in self._text_input:
            if name == "attention_mask":
                feed[name] = (ids != self.spec.pad_token).astype(np.int64)
            else:
                feed[name] = ids
        e = sess.run([self._text_output], feed)[0].astype(np.float32)
        return e / np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-8)

    # ---------- классификация ----------

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        logits = logits - logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=1, keepdims=True)

    def zero_shot(self, emb: np.ndarray) -> np.ndarray:
        return self._softmax(100.0 * emb @ self.class_emb.T)

    def classify(self, emb: np.ndarray) -> np.ndarray:
        p = self.zero_shot(emb)
        head = self.heads.get("category")
        if head is not None and len(emb):
            p = head.blend(emb, p, self.class_keys)
        return p

    def bunk_scores(self, emb: np.ndarray) -> np.ndarray:
        """Вероятность «двухъярусная кровать» для вырезок кроватей (столбец 0)."""
        p = self._softmax(100.0 * emb @ self.bunk_emb.T)
        head = self.heads.get("bunk")
        if head is not None and len(emb):
            p = head.blend(emb, p, self.bunk_keys)
        return p[:, 0]

    def watermark(self, emb: np.ndarray) -> np.ndarray:
        return emb @ self.watermark_emb

    def sub_scores(self, emb: np.ndarray, keys: list[str]) -> np.ndarray:
        idx = [self.sub_keys.index(k) for k in keys]
        p = self._softmax(100.0 * emb @ self.sub_emb[idx].T)
        group = "dorm_sub" if keys[0].startswith("dorm_") else "sport_sub" if keys[0].startswith("sport_") else ""
        head = self.heads.get(group)
        if head is not None and len(emb):
            p = head.blend(emb, p, keys)
        return p

    def warmup(self) -> None:
        """Первый прогон прогревает аллокаторы: иначе первое настоящее фото считается в разы дольше."""
        self.embed_images([Image.new("RGB", (self.spec.image_size, self.spec.image_size), (128, 128, 128))])

    def info(self) -> dict[str, Any]:
        return {"model": self.model_id, "runtime": "onnxruntime", "image_size": self.spec.image_size,
                "dim": self.dim, "heads": sorted(self.heads)}


def get_clip() -> ClipModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = ClipModel()
    return _model
