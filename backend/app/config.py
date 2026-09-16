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
    contact: str = "https://github.com/your-team/candid-ai"

    # OpenCLIP: архитектура и веса. CLIP_PRETRAINED — тег open_clip (скачивается с Hugging Face Hub при сборке образа),
    # CLIP_WEIGHTS — локальный файл, используется, если тег не задан или недоступен.
    clip_arch: str = "ViT-B-32-quickgelu"
    clip_pretrained: str = ""  # например laion2b_s34b_b79k вместе с CLIP_ARCH=ViT-B-32; головы тогда надо переобучить
    clip_fallback_arch: str = "ViT-B-32-quickgelu"
    clip_weights: str = "models/vit_b_32-quickgelu-laion400m_e32.pt"
    heads_dir: str = "ml/heads"
    yolo_weights: str = "models/yolo11s.pt"
    torch_threads: int = 2

    rate_limit_per_min: int = 8
    cache_ttl_s: int = 6 * 3600
    cache_dir: str = "/tmp/candid-cache"
    osm_cache_ttl_s: int = 7 * 24 * 3600
    context_cache_ttl_s: int = 14 * 24 * 3600
    prewarm: bool = True

    # Бюджеты времени (секунды)
    resolve_timeout: float = 7.0
    source_timeout: float = 11.0
    osm_timeout: float = 9.0
    osm_background_timeout: float = 45.0
    context_timeout: float = 8.0
    download_timeout: float = 6.0
    total_budget: float = 27.0

    max_downloads: int = 170
    download_concurrency: int = 20
    max_image_bytes: int = 6_000_000

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
    offline_fixtures: str = ""  # путь к фикстурам для офлайн-режима тестов

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else ROOT / p

    @property
    def user_agent(self) -> str:
        return f"CandidAI/0.1 (LOCUS Hackathon 2026 case 1; +{self.contact})"


@lru_cache
def get_settings() -> Settings:
    return Settings()
