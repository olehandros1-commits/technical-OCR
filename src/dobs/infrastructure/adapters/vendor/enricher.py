from __future__ import annotations

import logging

from dobs.application.ports.vendor_enricher import VendorEnricherPort
from dobs.application.ports.vendor_lookup import VendorLookupPort

log = logging.getLogger(__name__)


class VendorEnricher(VendorEnricherPort):
    def __init__(self, /, *, lookup: VendorLookupPort) -> None:
        self._lookup = lookup

    async def enrich_in_place(self, records: list[dict]) -> None:
        for rec in records:
            raw = rec.get("description") or ""
            try:
                info = await self._lookup.lookup(raw)
            except Exception as exc:
                log.warning("vendor enrich failed for %r: %s", raw[:40], exc)
                continue
            if info.canonical_name:
                rec["vendor"] = info.canonical_name
            if info.logo_url:
                rec["vendor_logo"] = info.logo_url
