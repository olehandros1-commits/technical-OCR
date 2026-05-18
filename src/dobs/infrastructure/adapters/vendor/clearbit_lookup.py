from __future__ import annotations

import json
import os
import re
from pathlib import Path

import aiosqlite
import httpx

from dobs.application.ports.vendor_lookup import VendorInfo, VendorLookupPort

_CACHE_PATH = Path(os.getenv("VENDOR_CACHE_DB", "out/vendor_cache.db"))


def _normalise_key(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower())[:80]


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS vendor_cache ("
        "  key        TEXT PRIMARY KEY,"
        "  payload    TEXT NOT NULL,"
        "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");"
    )
    await db.commit()


async def _cache_get(key: str) -> VendorInfo | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        async with aiosqlite.connect(_CACHE_PATH) as db:
            async with db.execute(
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


async def _cache_put(key: str, info: VendorInfo) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "raw": info.raw,
        "canonical_name": info.canonical_name,
        "category": info.category,
        "logo_url": info.logo_url,
        "country": info.country,
    })
    async with aiosqlite.connect(_CACHE_PATH) as db:
        await _ensure_schema(db)
        await db.execute(
            "INSERT OR REPLACE INTO vendor_cache (key, payload) VALUES (?, ?)",
            (key, payload),
        )
        await db.commit()


class ClearbitVendorLookup(VendorLookupPort):
    def __init__(
        self,
        /,
        *,
        timeout: float = 3.0,
    ) -> None:
        self._timeout = timeout

    async def lookup(self, raw: str) -> VendorInfo:
        raw = (raw or "").strip()
        if not raw:
            return VendorInfo(raw="", canonical_name=None)

        key = _normalise_key(raw)
        cached = await _cache_get(key)
        if cached is not None:
            return cached

        info = await self._fetch_clearbit(raw) or VendorInfo(raw=raw, canonical_name=raw.title())
        try:
            await _cache_put(key, info)
        except Exception:
            pass
        return info

    async def _fetch_clearbit(self, raw: str) -> VendorInfo | None:
        if os.getenv("VENDOR_DISABLE_CLEARBIT", "0") in {"1", "true"}:
            return None
        try:
            import urllib.parse
            q = urllib.parse.quote_plus(raw[:60])
            url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={q}"
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
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
