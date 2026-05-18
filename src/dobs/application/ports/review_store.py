from __future__ import annotations
from abc import abstractmethod
from typing import Literal, Protocol

Decision = Literal["approve", "reject", "edit", "pending"]


class ReviewStorePort(Protocol):
    @abstractmethod
    async def record(
        self,
        *,
        statement_key: str,
        tx_index: int,
        decision: Decision,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    async def latest_for_statement(self, statement_key: str) -> dict[int, dict]:
        raise NotImplementedError

    @abstractmethod
    async def history(self, statement_key: str, tx_index: int) -> list[dict]:
        raise NotImplementedError
