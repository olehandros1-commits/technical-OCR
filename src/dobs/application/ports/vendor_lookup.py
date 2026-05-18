from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class VendorInfo:
    raw: str
    canonical_name: str | None = None
    category: str | None = None
    logo_url: str | None = None
    country: str | None = None


class VendorLookupPort(Protocol):
    async def lookup(self, raw: str) -> VendorInfo: ...
