from __future__ import annotations

from dataclasses import dataclass

from dobs.application.config import TierRegistry
from dobs.domain.value_objects.tier import Tier


@dataclass(frozen=True, kw_only=True, slots=True)
class GetTiersQuery:
    pass


class GetTiersHandler:
    def __init__(self, /) -> None:
        pass

    async def __call__(self, query: GetTiersQuery) -> list[Tier]:
        return TierRegistry.all_tiers()
