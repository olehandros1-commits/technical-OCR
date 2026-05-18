from __future__ import annotations

from typing import Any, Protocol


class VendorEnricherPort(Protocol):
    async def enrich_in_place(self, records: list[dict[str, Any]]) -> None: ...
