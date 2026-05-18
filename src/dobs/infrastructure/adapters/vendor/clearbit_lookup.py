from __future__ import annotations

import json
import os
import re

import httpx

from dobs.application.ports.vendor_lookup import VendorInfo, VendorLookupPort
from dobs.infrastructure.persistence.sqlite_session import SqliteSessionFactory


VENDOR_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS vendor_cache (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class VendorCacheStore:
    def __init__(self, /, *, sessions: SqliteSessionFactory) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> VendorInfo | None:
        try:
            async with self._sessions.read_only() as session:
                async with session.execute(
                    "SELECT payload FROM vendor_cache WHERE key = ?", (key,)
                ) as cursor:
                    row = await cursor.fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            return VendorInfo(
                raw=data.get("raw", ""),
                canonical_name=data.get("canonical_name"),
                category=data.get("category"),
                logo_url=data.get("logo_url"),
                country=data.get("country"),
            )
        except Exception:
            return None

    async def put(self, key: str, info: VendorInfo) -> None:
        payload = json.dumps({
            "raw": info.raw,
            "canonical_name": info.canonical_name,
            "category": info.category,
            "logo_url": info.logo_url,
            "country": info.country,
        })
        async with self._sessions.session() as session:
            await session.execute(
                "INSERT OR REPLACE INTO vendor_cache (key, payload) VALUES (?, ?)",
                (key, payload),
            )


class ClearbitVendorLookup(VendorLookupPort):
    _CLEARBIT_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"

    def __init__(
        self,
        /,
        *,
        cache: VendorCacheStore | None = None,
        timeout: float = 3.0,
    ) -> None:
        self._cache = cache
        self._timeout = timeout

    @staticmethod
    def _normalise_key(raw: str) -> str:
        return re.sub(r"\s+", " ", (raw or "").strip().lower())[:80]

    async def lookup(self, raw: str) -> VendorInfo:
        raw = (raw or "").strip()
        if not raw:
            return VendorInfo(raw="", canonical_name=None)

        key = self._normalise_key(raw)
        if self._cache is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                return cached

        info = await self._fetch_clearbit(raw) or VendorInfo(raw=raw, canonical_name=raw.title())
        if self._cache is not None:
            try:
                await self._cache.put(key, info)
            except Exception:
                pass
        return info

    async def _fetch_clearbit(self, raw: str) -> VendorInfo | None:
        if os.getenv("VENDOR_DISABLE_CLEARBIT", "0") in {"1", "true"}:
            return None
        try:
            import urllib.parse
            q = urllib.parse.quote_plus(raw[:60])
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._CLEARBIT_URL}?query={q}")
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        if not data:
            return None
        top = data[0]
        return VendorInfo(
            raw=raw,
            canonical_name=top.get("name") or raw,
            logo_url=top.get("logo"),
            country=None,
            category=None,
        )
