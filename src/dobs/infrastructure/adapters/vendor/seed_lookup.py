from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dobs.application.ports.vendor_lookup import VendorInfo, VendorLookupPort

_SEEDS_PATH = Path(os.getenv("VENDOR_SEEDS_FILE", "out/vendor_seeds.json"))


def _normalise_key(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower())[:80]


def _load_seeds(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {_normalise_key(k): v for k, v in data.items()}
    except Exception:
        return {}


class SeedVendorLookup(VendorLookupPort):
    def __init__(
        self,
        /,
        *,
        seeds_path: Path = _SEEDS_PATH,
    ) -> None:
        self._seeds: dict[str, dict[str, object]] = _load_seeds(seeds_path)

    async def lookup(self, raw: str) -> VendorInfo:
        raw = (raw or "").strip()
        if not raw:
            return VendorInfo(raw="", canonical_name=None)

        key = _normalise_key(raw)
        seed = self._seeds.get(key)

        if not seed:
            for sk, sv in self._seeds.items():
                if sk and (sk in key or key.startswith(sk)):
                    seed = sv
                    break

        if not seed:
            return VendorInfo(raw=raw, canonical_name=None)

        return VendorInfo(
            raw=raw,
            canonical_name=str(seed.get("name") or raw.title()),
            logo_url=str(seed["logo_url"]) if seed.get("logo_url") else None,
            country=str(seed["country"]) if seed.get("country") else None,
            category=str(seed["category"]) if seed.get("category") else None,
        )
