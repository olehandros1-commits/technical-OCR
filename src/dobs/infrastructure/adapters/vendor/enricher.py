from __future__ import annotations

import asyncio
import logging
from typing import Any

from dobs.application.ports.vendor_enricher import VendorEnricherPort
from dobs.application.ports.vendor_lookup import VendorInfo, VendorLookupPort

log = logging.getLogger(__name__)


class VendorEnricher(VendorEnricherPort):
    def __init__(self, /, *, lookup: VendorLookupPort) -> None:
        self._lookup = lookup

    async def enrich_in_place(self, records: list[dict[str, Any]]) -> None:
        descriptions = list({(rec.get("description") or "") for rec in records})
        if not descriptions:
            return

        async def _safe_lookup(desc: str) -> tuple[str, VendorInfo | None]:
            try:
                info = await self._lookup.lookup(desc)
                return desc, info
            except Exception as exc:
                log.warning("vendor enrich lookup failed for %r: %s", desc[:40], exc)
                return desc, None

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_safe_lookup(d)) for d in descriptions]
        by_desc = {r[0]: r[1] for r in (t.result() for t in tasks)}

        for rec in records:
            info = by_desc.get(rec.get("description") or "")
            if info is None:
                continue
            if info.canonical_name:
                rec["vendor"] = info.canonical_name
            if info.logo_url:
                rec["vendor_logo"] = info.logo_url
