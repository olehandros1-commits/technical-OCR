from __future__ import annotations

from dataclasses import dataclass

from dobs.application.ports.audit_sink import AuditSinkPort


@dataclass(frozen=True, kw_only=True, slots=True)
class GetAuditLogQuery:
    limit: int = 50


class GetAuditLogHandler:
    def __init__(
        self,
        /,
        *,
        audit: AuditSinkPort,
    ) -> None:
        self._audit = audit

    async def __call__(self, query: GetAuditLogQuery) -> list[dict[str, object]]:
        return await self._audit.recent(limit=query.limit)
