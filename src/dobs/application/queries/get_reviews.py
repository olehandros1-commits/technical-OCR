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

    async def __call__(self, query: GetReviewsQuery) -> list[dict[str, object]]:
        latest = await self._review_store.latest_for_statement(query.statement_key)
        return list(latest.values())
