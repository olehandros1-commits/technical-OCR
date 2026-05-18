"""Stage 4.5: enrich already-extracted transactions.

After the main extraction we run a single batched call that adds two
fields per transaction:
  * category: one of a small fixed taxonomy (PAYABLE / CHECK / WIRE / ...)
  * vendor: normalised vendor name (when identifiable)
  * confidence: model's self-reported confidence 0-1

This is a separate stage on purpose -- it keeps the extraction prompt small
(more accurate) and lets us cache the enrichment independently. It is also
cheap: the per-row description is short, so we can batch the whole list
into one call.
"""
from __future__ import annotations
import json
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from extractor.backends import LLMBackend
from extractor.backends.base import LLMRole
from extractor.schemas import Transaction, TxCategory


_SYSTEM = """You categorise bank transactions and assess your own confidence
that each row is correct.

You will receive a JSON array of {index, description, deposit, withdrawal}
records. For each row return:
  * index: the SAME index from the input (so the caller can match).
  * category: one of:
      ACH_PAYABLE       - generic AP / payables ACH (e.g. "PAYABLES 1452...")
      WIRE              - wire transfer
      CHECK             - paper check ("CHECK #40788", etc.)
      DEPOSIT_REMOTE    - remote deposit / mobile deposit
      DEPOSIT_CASH      - branch or ATM cash deposit
      TRANSFER_INTERNAL - movement between own accounts ("TRNSFR TO/FROM CHECKING")
      PAYROLL           - payroll run
      VENDOR_PAYMENT    - identifiable vendor receivable/payable
      CARD_PAYMENT      - Amex / Visa / Mastercard payment
      LOAN_PAYMENT      - loan, mortgage, SBA EIDL repayment
      INTEREST          - interest paid by the bank
      FEE               - service charge, bank fee, NSF fee
      TAX               - tax payment (IRS / state)
      OTHER             - anything else
  * vendor: short normalised vendor name if you can extract one (e.g.
    "Genuine Parts", "Mid Atlantic Trust", "Cardmember Services"); null
    when the description is generic ("REMOTE DEPOSIT") or unreadable.
  * confidence: 0.0-1.0 self-reported certainty that the (date, amount,
    side) is correct as recorded. Use:
      1.0  - obvious, clean row
      0.7  - small wording ambiguity but amount/side certain
      0.4  - description partially redacted or wrapped weirdly
      0.0  - cannot verify at all

Return a single JSON object {"items": [...]}.
"""


class _EnrichedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    category: TxCategory
    vendor: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class _EnrichResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[_EnrichedItem]


def enrich_transactions(
    transactions: list[Transaction],
    backend: LLMBackend,
    *,
    batch_size: int = 80,
) -> list[Transaction]:
    """Mutate-and-return: adds category/vendor/confidence to each transaction.

    Batched in groups of `batch_size` to keep the output tokens per call
    bounded.
    """
    if not transactions:
        return transactions

    out = list(transactions)  # shallow copy of refs
    for start in range(0, len(out), batch_size):
        batch = out[start:start + batch_size]
        records = [
            {
                "index": start + i,
                "description": t.description,
                "deposit": t.deposit,
                "withdrawal": t.withdrawal,
            }
            for i, t in enumerate(batch)
        ]
        user = (
            "Categorise these transactions and rate your confidence. "
            "Return a JSON object {\"items\": [...]} with one item per row.\n\n"
            f"{json.dumps(records, indent=2)}"
        )
        try:
            # Categorisation + confidence is a tagging task -- Haiku on
            # Anthropic / qwen2.5:7b on Ollama handles it accurately and
            # at ~10x lower cost than Sonnet.
            resp = backend.call_structured(
                system=_SYSTEM,
                user=user,
                response_model=_EnrichResponse,
                role=LLMRole.CHEAP,
            )
        except Exception:
            # Enrichment failure must not break extraction. Skip this batch.
            continue
        by_index = {item.index: item for item in resp.items}
        for i in range(start, min(start + batch_size, len(out))):
            item = by_index.get(i)
            if item is None:
                continue
            t = out[i]
            t.category = item.category
            t.vendor = item.vendor
            t.confidence = item.confidence
    return out
