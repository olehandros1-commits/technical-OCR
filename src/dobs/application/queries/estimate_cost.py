from __future__ import annotations

from dataclasses import dataclass

from dobs.application.services.cost_estimate import CostEstimate, estimate


@dataclass(frozen=True, kw_only=True, slots=True)
class EstimateCostQuery:
    statements: int
    enrich: bool = False
    backend: str = "anthropic"
    chunks_per_statement: int = 4
    avg_repair_attempts: float = 0.5


class EstimateCostHandler:
    def __init__(self, /) -> None:
        pass

    async def __call__(self, query: EstimateCostQuery) -> CostEstimate:
        return estimate(
            query.statements,
            enrich=query.enrich,
            backend=query.backend,
            chunks_per_statement=query.chunks_per_statement,
            avg_repair_attempts=query.avg_repair_attempts,
        )
