"""Vendor enrichment: turn 'GENUINE PARTS CO/ACH' into a polished vendor card.

Three sources, tried in order, each gracefully optional:

  1. Local seed dictionary (`vendor_seeds.json` if present) -- zero-cost,
     deterministic, perfect for the 20 vendors a small business sees
     monthly.
  2. Clearbit Autocomplete + Logo API (free tier) -- needs no API key
     for autocomplete; returns logo URL + canonical name.
  3. Brave Search Web API (if BRAVE_API_KEY set) -- broader coverage.

Falls through to a `VendorInfo(canonical_name=raw)` stub when nothing
matches. The pipeline NEVER fails because of vendor lookup.

We cache vendor lookups in `out/vendor_cache.db` so a vendor name is
hit at most once across all extractions.
"""
from __future__ import annotations
import json
import logging
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class VendorInfo:
    raw: str
    canonical_name: str
    logo_url: Optional[str] = None
    domain: Optional[str] = None
    source: str = "stub"   # "seed" | "clearbit" | "brave" | "stub"

    def to_dict(self) -> dict:
        return asdict(self)


_CACHE_PATH = Path(os.getenv("VENDOR_CACHE_DB", "out/vendor_cache.db"))
_LOCK = threading.Lock()


def _normalise_key(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower())[:80]


def _cache_init() -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, sqlite3.connect(_CACHE_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vendor_cache (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


def _cache_get(key: str) -> Optional[VendorInfo]:
    if not _CACHE_PATH.exists():
        return None
    with _LOCK, sqlite3.connect(_CACHE_PATH) as conn:
        row = conn.execute(
            "SELECT payload FROM vendor_cache WHERE key = ?", (key,),
        ).fetchone()
    if not row:
        return None
    return VendorInfo(**json.loads(row[0]))


def _cache_put(key: str, info: VendorInfo) -> None:
    _cache_init()
    with _LOCK, sqlite3.connect(_CACHE_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vendor_cache (key, payload) VALUES (?, ?)",
            (key, json.dumps(info.to_dict())),
        )


def _load_seeds() -> dict[str, dict]:
    seed_path = Path(os.getenv("VENDOR_SEEDS_FILE", "out/vendor_seeds.json"))
    if not seed_path.exists():
        return {}
    try:
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        return {_normalise_key(k): v for k, v in data.items()}
    except Exception as e:
        log.warning("vendor seeds load failed: %s", e)
        return {}


_SEEDS_CACHE: dict[str, dict] | None = None


def _seeds() -> dict[str, dict]:
    global _SEEDS_CACHE
    if _SEEDS_CACHE is None:
        _SEEDS_CACHE = _load_seeds()
    return _SEEDS_CACHE


# ---------- Lookup paths --------------------------------------------------

def _lookup_seed(raw: str) -> Optional[VendorInfo]:
    key = _normalise_key(raw)
    seed = _seeds().get(key)
    if not seed:
        # Fuzzy prefix match: "genuine parts" in seed key matches
        # "genuine parts co/ach".
        for sk, sv in _seeds().items():
            if sk and (sk in key or key.startswith(sk)):
                seed = sv
                break
    if not seed:
        return None
    return VendorInfo(
        raw=raw,
        canonical_name=seed.get("name") or raw.title(),
        logo_url=seed.get("logo_url"),
        domain=seed.get("domain"),
        source="seed",
    )


def _lookup_clearbit(raw: str) -> Optional[VendorInfo]:
    """Clearbit's Autocomplete endpoint is free + no-key."""
    if os.getenv("VENDOR_DISABLE_CLEARBIT", "0") in {"1", "true"}:
        return None
    try:
        import urllib.request, urllib.parse
        q = urllib.parse.quote_plus(raw[:60])
        url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={q}"
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read())
    except Exception as e:
        log.debug("clearbit lookup failed: %s", e)
        return None
    if not data:
        return None
    top = data[0]
    return VendorInfo(
        raw=raw,
        canonical_name=top.get("name") or raw,
        logo_url=top.get("logo"),
        domain=top.get("domain"),
        source="clearbit",
    )


# ---------- Public entry point -------------------------------------------

def lookup_vendor(raw: str) -> VendorInfo:
    """Resolve a vendor string to a polished VendorInfo. Never raises."""
    raw = (raw or "").strip()
    if not raw:
        return VendorInfo(raw="", canonical_name="", source="stub")
    key = _normalise_key(raw)

    cached = _cache_get(key)
    if cached is not None:
        return cached

    info = (
        _lookup_seed(raw)
        or _lookup_clearbit(raw)
        or VendorInfo(raw=raw, canonical_name=raw.title(), source="stub")
    )
    try:
        _cache_put(key, info)
    except Exception as e:
        log.debug("vendor cache write failed: %s", e)
    return info


def enrich_vendors_in_place(transactions: list) -> int:
    """For each transaction with a vendor, attach `_vendor_logo` and
    `_vendor_domain` if a polished lookup succeeded. Returns count enriched.

    This mutates `transactions` (dicts) so the API response carries the
    extra UI-friendly fields without changing the Pydantic contract.
    """
    n = 0
    for t in transactions:
        v = t.get("vendor")
        if not v:
            continue
        info = lookup_vendor(v)
        if info.source == "stub":
            continue
        t["_vendor_logo"] = info.logo_url
        t["_vendor_domain"] = info.domain
        t["_vendor_canonical"] = info.canonical_name
        n += 1
    return n
