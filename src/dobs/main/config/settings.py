from __future__ import annotations

import os


class AppSettings:
    def __init__(self) -> None:
        self.anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
        self.ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.backend: str | None = os.getenv("EXTRACTOR_BACKEND")
        self.tier: str | None = os.getenv("EXTRACTOR_TIER")
        self.demo_replay: bool = os.getenv("EXTRACTOR_DEMO_REPLAY", "0") in {"1", "true"}
        self.cache_url: str | None = os.getenv("EXTRACTOR_CACHE_URL")
        self.api_keys: str | None = os.getenv("EXTRACTOR_API_KEYS")
        self.cors_allow: str | None = os.getenv("EXTRACTOR_CORS_ALLOW")
        self.spend_cap_usd: float | None = (
            float(os.getenv("EXTRACTOR_SPEND_CAP_USD"))
            if os.getenv("EXTRACTOR_SPEND_CAP_USD")
            else None
        )
        self.audit_log_db: str = os.getenv("AUDIT_LOG_DB", "out/audit.db")
        self.review_db: str = os.getenv("REVIEW_DB", "out/reviews.db")
        self.ocr_cache_db: str = os.getenv("OCR_CACHE_DB", "out/ocr_cache.db")
        self.vendor_cache_db: str = os.getenv("VENDOR_CACHE_DB", "out/vendor_cache.db")


def get_settings() -> AppSettings:
    return AppSettings()
