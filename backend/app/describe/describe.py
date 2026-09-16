"""Краткое описание кампуса строго по найденным текстам, со сносками на источники.

С ключом Gemini: модель пишет предложения и указывает номера источников, затем каждое
предложение проверяется (источники существуют, числа есть в источниках). Непроверенные
предложения удаляются. Без ключа: выдержки из Википедии и сайта вуза без генерации.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings
from ..domain import University
from ..http import client

_BOUNDARY = re.compile(r"[.!?]\s+(?=[А-ЯЁA-ZӘҒҚҢӨҰҮҺІ«\"(])")
_ABBR = re.compile(r"(\b[А-ЯЁA-ZӘҒҚҢӨҰҮҺІ]|\bим|\bг|\bул|\bт\.д|\bт\.е|\bпр|\bим\.|\bсм|\bок)$")


def split_sentences(text: str) -> list[str]:
    out, start = [], 0
    for m in _BOUNDARY.finditer(text):
        head = text[start:m.start()]
        if _ABBR.search(head):
            continue
        out.append(text[start:m.start() + 1].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


@dataclass
class SourceText:
    id: str
    title: str
    url: str
    kind: str
    lang: str
    text: str


def collect(uni: University, wiki: list[dict[str, Any]], pages: list[Any]) -> list[SourceText]:
    out: list[SourceText] = []
    for w in wiki:
        out.append(SourceText(id="", title=f"Википедия ({w['lang']}): {w['title']}", url=w["url"], kind="wikipedia", lang=w["lang"], text=w["extract"][:1800]))
    for p in pages[:6]:
        text = " ".join(t for t in (p.description, p.text) if t)
        if len(text) > 120:
            out.append(SourceText(id="", title=f"Сайт вуза: {p.title[:80]}", url=p.url, kind="official", lang="", text=text[:1500]))
    for i, s in enumerate(out, 1):
        s.id = f"S{i}"
    return out


def validate(sentences: list[dict[str, Any]], sources: list[SourceText]) -> list[dict[str, Any]]:
    by_id = {s.id: s for s in sources}
    ok = []
    for item in sentences:
        text = str(item.get("text", "")).strip().replace("—", ",")
        ids = [i for i in item.get("sources", []) if i in by_id]
        if not text or not ids:
            continue
        cited = " ".join(by_id[i].text for i in ids)
        cited_nums = {re.sub(r"\s", "", n) for n in re.findall(r"\d[\d\s]*\d|\d", cited)}
        nums = {re.sub(r"\s", "", n) for n in re.findall(r"\d[\d\s]*\d|\d", text)}
        if nums - cited_nums:
            continue
        ok.append({"text": text, "sources": ids})
    return ok


PROMPT = """Ты помогаешь абитуриенту понять, как устроен университет «{name}».
Ниже пронумерованные фрагменты источников. Напиши 3–5 коротких предложений на русском языке
о кампусе, учебных корпусах, общежитиях, библиотеке, спорте и студенческой жизни, используя ТОЛЬКО факты из фрагментов.
Не добавляй ничего, чего нет во фрагментах. Не используй рекламные оценки. Не используй длинное тире.
Каждое предложение сопроводи списком номеров фрагментов, из которых взят факт.
Ответ строго в JSON: {{"sentences": [{{"text": "...", "sources": ["S1"]}}]}}

Фрагменты:
{fragments}"""


async def with_gemini(uni: University, sources: list[SourceText]) -> list[dict[str, Any]]:
    s = get_settings()
    fragments = "\n\n".join(f"[{src.id}] {src.title}\n{src.text}" for src in sources)
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(name=uni.label, fragments=fragments)}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json", "maxOutputTokens": 900},
    }
    c = await client()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{s.gemini_model}:generateContent"
    r = await c.post(url, json=body, headers={"x-goog-api-key": s.gemini_api_key}, timeout=14)
    r.raise_for_status()
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()))
    return validate(parsed.get("sentences", []), sources)


def extractive(sources: list[SourceText]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    wiki = sorted([s for s in sources if s.kind == "wikipedia"], key=lambda s: {"ru": 0, "en": 1, "kk": 2}.get(s.lang, 3))
    if wiki:
        src = wiki[0]
        for sent in split_sentences(src.text)[:3]:
            sent = sent.strip().replace(" — ", ": ", 1).replace("—", ",")
            if len(sent) > 25:
                out.append({"text": sent, "sources": [src.id]})
    official = next((s for s in sources if s.kind == "official" and len(s.text) > 120), None)
    if official and len(out) < 4:
        first = split_sentences(official.text)[0][:280].strip()
        known = " ".join(x["text"] for x in out).lower()
        if len(first) > 40 and first.lower()[:40] not in known:
            out.append({"text": first, "sources": [official.id]})
    return out


async def describe(uni: University, sources: list[SourceText]) -> dict[str, Any]:
    s = get_settings()
    public_sources = [{"id": x.id, "title": x.title, "url": x.url, "kind": x.kind} for x in sources]
    if not sources:
        return {"mode": "none", "sentences": [], "sources": [], "message": "Текстовых источников о кампусе не найдено."}
    if s.gemini_api_key:
        try:
            sentences = await with_gemini(uni, sources)
            if sentences:
                return {"mode": "gemini", "model": s.gemini_model, "sentences": sentences, "sources": public_sources}
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            pass
    return {"mode": "extractive", "sentences": extractive(sources), "sources": public_sources}
