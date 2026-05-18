from __future__ import annotations
from abc import abstractmethod
from typing import Protocol

from src.dobs.domain.entities.audit_record import AuditRecord


class AuditSinkPort(Protocol):
    @abstractmethod
    async def record(self, started_at: float, record: AuditRecord) -> int:
        raise NotImplementedError

    @abstractmethod
    async def recent(self, limit: int = 50) -> list[AuditRecord]:
        raise NotImplementedError
