from __future__ import annotations

from dataclasses import dataclass

from dobs.application.ports.review_store import ReviewStorePort


@dataclass(frozen=True, kw_only=True, slots=True)
class GetReviewsQuery:
    statement_key: str


class GetReviewsHandler:
    def __init__(
        self,
        /,
        *,
        review_store: ReviewStorePort,
    ) -> None:
        self._review_store = review_store

    async def __call__(self, query: GetReviewsQuery) -> list[dict]:
        return await self._review_store.get_decisions(query.statement_key)
