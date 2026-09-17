from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    flickr_api_key: str = ""
    contact: str = "https://github.com/zhomarterkhainar-svg/locus"

    # ---------- модели (ONNX Runtime, без torch) ----------
    # clip_model: ключ из backend/app/vision/onnx_backend.py MODELS.
    # clip_vitb32 - CLIP ViT-B/32 int8: 15 мс на фото на 4 потоках (замеры в ml/BENCHMARK.md).
    clip_model: str = "clip_vitb32"
    models_dir: str = "models"
    prompts_dir: str = "ml/prompts"
    heads_dir: str = "ml/heads"
    onnx_threads: int = 0  # 0 - по числу ядер
    onnx_mem_arena: bool = True  # на инстансе с 512 МБ выключаем: MEM_ARENA=false

    # ---------- ограничения и кэш ----------
    rate_limit_per_min: int = 12
    cache_ttl_s: int = 6 * 3600
    cache_dir: str = "/tmp/candid-cache"
    seed_cache_dir: str = "backend/seed_cache"  # заранее собранные карты OSM частых вузов (раскрыто в README)
    seed_cache_ttl_s: int = 120 * 24 * 3600
    osm_cache_ttl_s: int = 7 * 24 * 3600
    context_cache_ttl_s: int = 14 * 24 * 3600
    prewarm: bool = True

    # ---------- Supabase (общий кэш профилей, карт и отметок между инстансами) ----------
    supabase_url: str = ""
    supabase_key: str = ""  # service_role, только на сервере
    supabase_timeout: float = 3.0

    # ---------- бюджеты времени (секунды) ----------
    # Цель: полезный профиль за 10 секунд. Источники, не успевшие ответить, отменяются,
    # интерфейс об этом сообщает, а догрузка продолжается в фоне и попадает в кэш.
    resolve_timeout: float = 4.0
    source_timeout: float = 6.0
    osm_timeout: float = 3.0
    osm_background_timeout: float = 200.0  # публичные зеркала Overpass в часы пик отвечают минутами
    context_timeout: float = 5.0
    download_timeout: float = 4.0
    total_budget: float = 10.0
    facts_budget: float = 3.0
    # Потолок всей сборки. Бюджет выше - это цель «когда профиль уже полезен»; проверка уже
    # скачанных фото после него не обрывается, иначе на слабом инстансе (Render free - доля ядра)
    # партия не успевает досчитаться и профиль остаётся пустым при полсотне скачанных файлов.
    analyze_budget: float = 75.0
    source_grace: float = 4.0  # отсрочка источникам, если проверенных фото почти нет
    first_paint_target: float = 3.5  # к этому моменту стараемся показать первые подтверждённые фото
    ready_min_photos: int = 6  # столько подтверждённых фото считаем полезным профилем
    ready_min_categories: int = 2
    analyze_chunk: int = 12  # размер партии «скачали - посчитали - показали»

    max_downloads: int = 120
    download_concurrency: int = 32
    per_host_downloads: int = 8  # одновременных загрузок с одного сайта
    cdn_host_downloads: int = 12  # с CDN Wikimedia и Flickr можно больше, чем с сайта вуза
    decode_concurrency: int = 3  # одновременных декодирований: декодер держит GIL
    max_image_bytes: int = 3_000_000
    analyze_side: int = 512  # до какого размера ужимаем кадр в памяти перед анализом
    max_detect: int = 10  # сколько фото общежитий отдаём детектору предметов

    overpass_urls: list[str] = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]
    osrm_foot_url: str = "https://routing.openstreetmap.de/routed-foot/route/v1/driving"
    osrm_car_url: str = "https://routing.openstreetmap.de/routed-car/route/v1/driving"
    climate_url: str = "https://archive-api.open-meteo.com/v1/archive"

    frontend_dist: str = "frontend/dist"
    # Домены фронтенда, которым разрешён доступ к API (Vercel + локальная разработка).
    # 5173 - vite dev, 4173 - vite preview (проверка собранной версии перед публикацией).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
    offline_fixtures: str = ""  # путь к фикстурам для офлайн-режима тестов

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else ROOT / p

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def user_agent(self) -> str:
        return f"CandidAI/1.0 (LOCUS Hackathon 2026 case 1; +{self.contact})"

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
