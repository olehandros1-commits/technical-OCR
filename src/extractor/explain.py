"""LLM-generated explanation for one flagged anomaly.

The anomaly detector and forensic stages tell you WHAT is suspicious.
This module tells the user WHY in plain English -- "this looks like
double-billing because there's an identical $5,200 payment to the same
vendor 30 minutes apart on a weekend". Useful in the HITL review queue
where a human needs context to approve / reject quickly.

CHEAP-tier (Haiku / qwen 7b) call -- one anomaly at a time so failures
don't poison the batch, and the cost stays under $0.001 per click.
"""
from __future__ import annotations
import json
from pydantic import BaseModel, ConfigDict

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole


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


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    suggested_action: str


def explain_anomaly(
    backend: LLMBackend,
    *,
    anomaly: dict,
    transaction: dict | None = None,
    context_transactions: list[dict] | None = None,
) -> Explanation:
    """Returns a short explanation + suggested action.

    `context_transactions` should include same-day or related rows so
    the model can spot patterns (e.g. duplicate amount within 24h).
    """
    user = (
        "## Anomaly\n"
        + json.dumps(anomaly, indent=2)
        + ("\n\n## Flagged transaction\n" + json.dumps(transaction, indent=2)
           if transaction else "")
        + ("\n\n## Nearby transactions for context\n" + json.dumps(
            (context_transactions or [])[:10], indent=2)
           if context_transactions else "")
    )
    return backend.call_structured(
        system=_SYSTEM,
        user=user,
        response_model=Explanation,
        role=LLMRole.CHEAP,
    )
