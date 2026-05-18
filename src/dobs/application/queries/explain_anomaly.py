from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.value_objects.llm_role import LLMRole

_SYSTEM = """You explain why a flagged bank-statement transaction
looks suspicious. The deterministic detector has already decided this
row is anomalous; your job is to write a short, plain-English
explanation a finance reviewer can act on.

Constraints:
  * 1-3 sentences, plain English, no jargon.
  * Reference concrete numbers / dates / vendors from the input.
  * Suggest a single concrete next action ("verify with vendor",
    "approve as recurring", "ask treasury", "ignore").
  * If you can't justify the flag from the data given, say so honestly.
"""


class ExplainAnomalyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    suggested_action: str


@dataclass(frozen=True, kw_only=True, slots=True)
class ExplainAnomalyQuery:
    anomaly: dict[str, Any]
    transaction: dict[str, Any] | None = None
    context_transactions: list[dict[str, Any]] | None = None


class ExplainAnomalyHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
    ) -> None:
        self._llm = llm

    async def __call__(self, query: ExplainAnomalyQuery) -> ExplainAnomalyResult:
        user = (
            "## Anomaly\n"
            + json.dumps(query.anomaly, indent=2)
            + (
                "\n\n## Flagged transaction\n" + json.dumps(query.transaction, indent=2)
                if query.transaction
                else ""
            )
            + (
                "\n\n## Nearby transactions for context\n"
                + json.dumps((query.context_transactions or [])[:10], indent=2)
                if query.context_transactions
                else ""
            )
        )
        return await self._llm.call_structured(
            system=_SYSTEM,
            user=user,
            response_model=ExplainAnomalyResult,
            role=LLMRole.CHEAP,
        )
