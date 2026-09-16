"""OpenCLIP: эмбеддинги изображений и zero-shot вероятности категорий."""
from __future__ import annotations

import threading

import numpy as np

from ..config import get_settings
from .categories import CATEGORIES, SUB_PROMPTS, TRASH, WATERMARK_PROMPTS

_lock = threading.Lock()
_model = None


class ClipModel:
    def __init__(self) -> None:
        import open_clip
        import torch

        s = get_settings()
        torch.set_num_threads(max(1, s.torch_threads))
        weights = s.path(s.clip_weights)
        pretrained = str(weights) if weights.exists() else s.clip_weights
        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(s.clip_arch, pretrained=pretrained)
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(s.clip_arch)
        self.name = f"OpenCLIP {s.clip_arch} ({weights.name if weights.exists() else s.clip_weights})"

        self.class_keys = list(CATEGORIES) + [f"trash:{k}" for k in TRASH]
        class_prompts = [CATEGORIES[k][1] for k in CATEGORIES] + [TRASH[k][1] for k in TRASH]
        self.class_emb = np.stack([self._mean_text(p) for p in class_prompts])
        self.watermark_emb = self._mean_text(WATERMARK_PROMPTS)
        self.sub_keys = list(SUB_PROMPTS)
        self.sub_emb = np.stack([self._mean_text(SUB_PROMPTS[k]) for k in self.sub_keys])

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

    def classify(self, emb: np.ndarray) -> np.ndarray:
        logits = 100.0 * emb @ self.class_emb.T
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=1, keepdims=True)

    def watermark(self, emb: np.ndarray) -> np.ndarray:
        return emb @ self.watermark_emb

    def sub_scores(self, emb: np.ndarray, keys: list[str]) -> np.ndarray:
        idx = [self.sub_keys.index(k) for k in keys]
        logits = 100.0 * emb @ self.sub_emb[idx].T
        logits -= logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=1, keepdims=True)


def get_clip() -> ClipModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = ClipModel()
    return _model
