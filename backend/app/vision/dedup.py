"""Дубликаты: точные копии по перцептивному хэшу и визуально похожие по эмбеддингам CLIP.

pHash считается на numpy (матрица DCT-II 32×32), а не библиотекой imagehash: результат тот же,
но в зависимостях нет scipy и PyWavelets - это минус ~60 МБ образа и заметно более быстрый старт
на маленьком инстансе.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from PIL import Image

PHASH_EXACT = 6
COSINE_NEAR = 0.955
HASH_SIZE = 8
HIGHFREQ = 4


@lru_cache(maxsize=4)
def _dct_matrix(n: int) -> np.ndarray:
    """Матрица DCT-II без нормировки - как scipy.fftpack.dct(type=2), которую использует imagehash."""
    k = np.arange(n).reshape(-1, 1)
    i = np.arange(n).reshape(1, -1)
    return 2.0 * np.cos(np.pi * k * (2 * i + 1) / (2 * n))


@dataclass(frozen=True)
class PHash:
    bits: int  # 64 бита в целом числе

    def __sub__(self, other: "PHash") -> int:
        return int(bin(self.bits ^ other.bits).count("1"))

    def __str__(self) -> str:
        return f"{self.bits:016x}"


def phash(img: Image.Image, hash_size: int = HASH_SIZE, highfreq_factor: int = HIGHFREQ) -> PHash:
    size = hash_size * highfreq_factor
    small = img.convert("L").resize((size, size), Image.LANCZOS)
    a = np.asarray(small, dtype=np.float64)
    d = _dct_matrix(size)
    low = (d @ a @ d.T)[:hash_size, :hash_size]
    diff = low > np.median(low)
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(v)
    return PHash(bits)


@dataclass
class Cluster:
    id: str
    rep_index: int
    members: list[int] = field(default_factory=list)


class DedupIndex:
    """Инкрементальный индекс: фото приходят партиями по мере ответа источников."""

    def __init__(self) -> None:
        self.hashes: list[PHash] = []
        self.embs: list[np.ndarray] = []
        self.cluster_of: list[str] = []
        self.clusters: dict[str, Cluster] = {}

    def add(self, h: PHash, emb: np.ndarray, key: str) -> tuple[str, str | None]:
        """Возвращает (cluster_id, kind), где kind = None для нового кластера, 'exact' или 'near'."""
        best: tuple[str, str] | None = None
        if self.embs:
            sims = np.stack(self.embs) @ emb
            for i, sim in enumerate(sims):
                dist = h - self.hashes[i]
                if dist <= PHASH_EXACT:
                    best = (self.cluster_of[i], "exact")
                    break
                if sim >= COSINE_NEAR and best is None:
                    best = (self.cluster_of[i], "near")
        idx = len(self.embs)
        self.hashes.append(h)
        self.embs.append(emb)
        if best:
            cid, kind = best
            self.cluster_of.append(cid)
            self.clusters[cid].members.append(idx)
            return cid, kind
        cid = key
        self.cluster_of.append(cid)
        self.clusters[cid] = Cluster(id=cid, rep_index=idx, members=[idx])
        return cid, None
