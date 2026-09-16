"""Дубликаты: точные копии по перцептивному хэшу и визуально похожие по эмбеддингам CLIP."""
from __future__ import annotations

from dataclasses import dataclass, field

import imagehash
import numpy as np
from PIL import Image

PHASH_EXACT = 6
COSINE_NEAR = 0.955


def phash(img: Image.Image) -> imagehash.ImageHash:
    return imagehash.phash(img, hash_size=8)


@dataclass
class Cluster:
    id: str
    rep_index: int
    members: list[int] = field(default_factory=list)


class DedupIndex:
    """Инкрементальный индекс: фото приходят партиями по мере ответа источников."""

    def __init__(self) -> None:
        self.hashes: list[imagehash.ImageHash] = []
        self.embs: list[np.ndarray] = []
        self.cluster_of: list[str] = []
        self.clusters: dict[str, Cluster] = {}

    def add(self, h: imagehash.ImageHash, emb: np.ndarray, key: str) -> tuple[str, str | None]:
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
