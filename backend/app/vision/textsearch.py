"""Поиск внутри профиля текстом: «двухъярусные кровати», «бассейн», «зимой».

Запрос переводится на английский (словарь частых слов, при наличии ключа Gemini — переводом),
кодируется текстовой частью CLIP и сравнивается с эмбеддингами уже проверенных фото профиля.
"""
from __future__ import annotations

import re

import httpx
import numpy as np

from ..config import get_settings
from ..http import client
from ..textnorm import has_cyrillic, normalize

# Основы слов (ru/kk) -> английская фраза для CLIP
LEXICON: list[tuple[str, str]] = [
    ("двухъярус", "bunk beds"), ("двухярус", "bunk beds"), ("кроват", "beds"), ("төсек", "beds"),
    ("общежит", "a student dormitory room"), ("жатақхана", "a student dormitory room"), ("комнат", "a room"),
    ("кухн", "a kitchen"), ("душ", "a shower room"), ("туалет", "a bathroom"), ("санузел", "a bathroom"),
    ("бассейн", "a swimming pool"), ("спортзал", "a sports hall"), ("спорт", "sports facilities"), ("тренаж", "a gym with exercise machines"),
    ("стадион", "a stadium"), ("футбол", "a football field"), ("баскетбол", "a basketball court"), ("волейбол", "a volleyball court"),
    ("библиот", "a library"), ("кітапхана", "a library"), ("читальн", "a reading room"), ("книг", "bookshelves"),
    ("лаборатор", "a laboratory"), ("зертхана", "a laboratory"), ("химич", "a chemistry lab"), ("робот", "robotics"),
    ("аудитор", "a lecture hall"), ("амфитеатр", "a tiered lecture hall"), ("лекци", "a lecture"), ("класс", "a classroom"),
    ("компьютер", "computers"), ("проектор", "a projector"), ("доск", "a whiteboard"),
    ("столов", "a cafeteria"), ("кафе", "a cafe"), ("еда", "food"), ("асхана", "a cafeteria"),
    ("корпус", "a university building"), ("фасад", "a building facade"), ("здани", "a building"), ("ғимарат", "a building"),
    ("кампус", "a university campus"), ("двор", "a courtyard"), ("парк", "a park"), ("зелен", "green trees and lawns"),
    ("зим", "in winter with snow"), ("снег", "snow"), ("лет", "in summer"), ("ночь", "at night"), ("ночн", "at night"),
    ("выпускн", "a graduation ceremony"), ("концерт", "a concert"), ("праздник", "a festival"), ("студент", "students"),
    ("конференц", "a conference"), ("актов", "an assembly hall"), ("музей", "a museum"), ("коворкинг", "a coworking space"),
    ("город", "a city street"), ("улиц", "a street"), ("мечет", "a mosque"), ("памятник", "a monument"), ("мост", "a bridge"),
    ("остановк", "a bus stop"), ("автобус", "a bus"), ("метро", "a metro station"), ("вход", "an entrance"), ("холл", "a lobby"),
]


def lexicon_translate(q: str) -> str | None:
    words = normalize(q).split()
    parts: list[str] = []
    for w in words:
        for stem, en in LEXICON:
            if w.startswith(stem) or (len(w) >= 5 and stem.startswith(w)):
                if en not in parts:
                    parts.append(en)
                break
    return ", ".join(parts) if parts else None


async def gemini_translate(q: str) -> str | None:
    s = get_settings()
    if not s.gemini_api_key:
        return None
    body = {
        "contents": [{"parts": [{"text": "Translate this photo search query from Russian or Kazakh into a short English phrase "
                                         "for an image search engine. Answer with the phrase only.\nQuery: " + q[:120]}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 30},
    }
    try:
        c = await client()
        r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{s.gemini_model}:generateContent",
                         json=body, headers={"x-goog-api-key": s.gemini_api_key}, timeout=4)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')
        return re.sub(r"\s+", " ", text)[:120] or None
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None


async def to_english(q: str) -> tuple[str | None, str]:
    q = q.strip()
    if not has_cyrillic(q):
        return q, "как есть"
    lex = lexicon_translate(q)
    if lex:
        return lex, "словарь"
    gem = await gemini_translate(q)
    if gem:
        return gem, "Gemini"
    return None, ""


def rank(text_emb: np.ndarray, ids: list[str], embs: np.ndarray, limit: int = 24) -> list[tuple[str, float]]:
    """Косинус запроса с фото. Порог относительный: CLIP даёт узкий диапазон сходств."""
    if not ids:
        return []
    sims = embs.astype(np.float32) @ text_emb.astype(np.float32)
    order = np.argsort(-sims)
    top = float(sims[order[0]])
    floor = max(0.17, top - 0.06)
    return [(ids[i], round(float(sims[i]), 4)) for i in order[:limit] if sims[i] >= floor]
