from __future__ import annotations

from typing import Protocol

from dobs.domain.entities.audit_record import AuditRecord


class AuditSinkPort(Protocol):
    async def record(self, started_at: float, record: AuditRecord) -> int: ...
    async def recent(self, limit: int = 50) -> list[dict[str, object]]: ...
