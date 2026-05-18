from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from dobs.domain.entities.base import Entity


@dataclass(eq=False, kw_only=True)
class AuditRecord(Entity[UUID]):
    tier: str | None = None
    backend: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None
    statement_count: int = 0
    reconciled_count: int = 0
    transactions_count: int = 0
    total_cost_usd: float = 0.0
    elapsed_s: float = 0.0
    prompts_hash: str = ""
    operator: str | None = None
    client_ip: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
