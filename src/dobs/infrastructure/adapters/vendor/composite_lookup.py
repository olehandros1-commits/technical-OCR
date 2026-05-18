from __future__ import annotations

from dobs.application.ports.vendor_lookup import VendorInfo, VendorLookupPort
from dobs.infrastructure.adapters.vendor.clearbit_lookup import ClearbitVendorLookup
from dobs.infrastructure.adapters.vendor.seed_lookup import SeedVendorLookup


class CompositeVendorLookup(VendorLookupPort):
    def __init__(
        self,
        /,
        *,
        seed: SeedVendorLookup,
        clearbit: ClearbitVendorLookup,
    ) -> None:
        self._seed = seed
        self._clearbit = clearbit

    async def lookup(self, raw: str) -> VendorInfo:
        seed_result = await self._seed.lookup(raw)
        if seed_result.canonical_name is not None:
            return seed_result

        clearbit_result = await self._clearbit.lookup(raw)
        if clearbit_result.canonical_name is not None:
            return clearbit_result

        return VendorInfo(raw=raw, canonical_name=raw.title() if raw else None)
