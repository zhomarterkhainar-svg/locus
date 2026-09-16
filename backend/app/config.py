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

    clip_arch: str = "ViT-B-32-quickgelu"
    clip_weights: str = "models/vit_b_32-quickgelu-laion400m_e32.pt"
    yolo_weights: str = "models/yolo11s.pt"
    torch_threads: int = 2

    rate_limit_per_min: int = 8
    cache_ttl_s: int = 6 * 3600

    # Бюджеты времени (секунды)
    resolve_timeout: float = 7.0
    source_timeout: float = 11.0
    osm_timeout: float = 9.0
    download_timeout: float = 6.0
    total_budget: float = 27.0

    max_downloads: int = 170
    download_concurrency: int = 20
    max_image_bytes: int = 6_000_000

    overpass_urls: list[str] = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]

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
