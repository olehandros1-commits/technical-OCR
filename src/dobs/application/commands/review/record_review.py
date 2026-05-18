from __future__ import annotations

from dataclasses import dataclass

from dobs.application.ports.review_store import Decision, ReviewStorePort


@dataclass(frozen=True, kw_only=True, slots=True)
class RecordReviewCommand:
    statement_key: str
    tx_index: int
    decision: Decision
    reviewer: str


class RecordReviewHandler:
    def __init__(
        self,
        /,
        *,
        review_store: ReviewStorePort,
    ) -> None:
        self._review_store = review_store

    async def __call__(self, command: RecordReviewCommand) -> None:
        await self._review_store.record(
            statement_key=command.statement_key,
            tx_index=command.tx_index,
            decision=command.decision,
            reviewer=command.reviewer,
        )
