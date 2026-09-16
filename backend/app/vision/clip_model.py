"""OpenCLIP: эмбеддинги изображений и zero-shot вероятности категорий."""
from __future__ import annotations

import threading

import numpy as np

from ..config import get_settings
from .categories import BUNK_PROMPTS, CATEGORIES, SUB_PROMPTS, TRASH, WATERMARK_PROMPTS
from .heads import Head, load_heads

_lock = threading.Lock()
_model = None


class ClipModel:
    def __init__(self) -> None:
        import open_clip
        import torch

        s = get_settings()
        torch.set_num_threads(max(1, s.torch_threads))
        self.torch = torch
        weights = s.path(s.clip_weights)
        loaded = False
        if s.clip_pretrained:
            try:
                self.model, _, self.preprocess = open_clip.create_model_and_transforms(s.clip_arch, pretrained=s.clip_pretrained)
                self.tokenizer = open_clip.get_tokenizer(s.clip_arch)
                self.model_id = f"{s.clip_arch}/{s.clip_pretrained}"
                loaded = True
            except Exception as e:  # noqa: BLE001
                import logging
                logging.getLogger("candid.clip").warning("не удалось загрузить %s/%s (%s), пробую локальные веса", s.clip_arch, s.clip_pretrained, e)
        if not loaded:
            arch = s.clip_fallback_arch
            pretrained = str(weights) if weights.exists() else "laion400m_e32"
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(arch, pretrained=pretrained)
            self.tokenizer = open_clip.get_tokenizer(arch)
            self.model_id = f"{arch}/laion400m_e32"
        self.model.eval()
        self.name = f"OpenCLIP {self.model_id}"
        self.heads: dict[str, Head] = load_heads(self.model_id)
        if self.heads:
            self.name += " + обученные головы (" + ", ".join(sorted(self.heads)) + ")"

        self.class_keys = list(CATEGORIES) + [f"trash:{k}" for k in TRASH]
        class_prompts = [CATEGORIES[k][1] for k in CATEGORIES] + [TRASH[k][1] for k in TRASH]
        self.class_emb = np.stack([self._mean_text(p) for p in class_prompts])
        self.watermark_emb = self._mean_text(WATERMARK_PROMPTS)
        self.sub_keys = list(SUB_PROMPTS)
        self.sub_emb = np.stack([self._mean_text(SUB_PROMPTS[k]) for k in self.sub_keys])
        self.bunk_keys = list(BUNK_PROMPTS)
        self.bunk_emb = np.stack([self._mean_text(BUNK_PROMPTS[k]) for k in self.bunk_keys])

    def _mean_text(self, prompts: list[str]) -> np.ndarray:
        with self.torch.no_grad():
            t = self.model.encode_text(self.tokenizer(prompts)).float()
            t = t / t.norm(dim=-1, keepdim=True)
            m = t.mean(dim=0)
            return (m / m.norm()).cpu().numpy()

    def embed_images(self, images: list) -> np.ndarray:
        out = []
        with self.torch.no_grad():
            for i in range(0, len(images), 32):
                batch = self.torch.stack([self.preprocess(im) for im in images[i:i + 32]])
                e = self.model.encode_image(batch).float()
                e = e / e.norm(dim=-1, keepdim=True)
                out.append(e.cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, self.class_emb.shape[1]), dtype=np.float32)

    def embed_text(self, texts: list[str]) -> np.ndarray:
        with self.torch.no_grad():
            t = self.model.encode_text(self.tokenizer(texts)).float()
            t = t / t.norm(dim=-1, keepdim=True)
        return t.cpu().numpy()

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


def get_clip() -> ClipModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = ClipModel()
    return _model
