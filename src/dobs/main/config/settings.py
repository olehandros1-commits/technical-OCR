from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    backend: str | None = Field(default=None, alias="EXTRACTOR_BACKEND")
    tier: str | None = Field(default=None, alias="EXTRACTOR_TIER")
    demo_replay: bool = Field(default=False, alias="EXTRACTOR_DEMO_REPLAY")
    cache_url: str | None = Field(default=None, alias="EXTRACTOR_CACHE_URL")
    api_keys: str | None = Field(default=None, alias="EXTRACTOR_API_KEYS")
    cors_allow: str | None = Field(default=None, alias="EXTRACTOR_CORS_ALLOW")
    spend_cap_usd: float | None = Field(default=None, alias="EXTRACTOR_SPEND_CAP_USD")
    audit_log_db: str = Field(default="out/audit.db", alias="AUDIT_LOG_DB")
    review_db: str = Field(default="out/reviews.db", alias="REVIEW_DB")
    ocr_cache_db: str = Field(default="out/ocr_cache.db", alias="OCR_CACHE_DB")
    vendor_cache_db: str = Field(default="out/vendor_cache.db", alias="VENDOR_CACHE_DB")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=False, alias="LOG_JSON")


def get_settings() -> AppSettings:
    return AppSettings()
