from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.domain.value_objects.transaction import Transaction
from dobs.domain.value_objects.tx_category import TxCategory

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
  * vendor: short normalised vendor name if you can extract one; null otherwise.
  * confidence: 0.0-1.0 self-reported certainty that the (date, amount,
    side) is correct as recorded.

Return a single JSON object {"items": [...]}.
"""


class _EnrichedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    category: TxCategory
    vendor: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class _EnrichResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[_EnrichedItem]


@dataclass(frozen=True, kw_only=True, slots=True)
class EnrichTransactionsCommand:
    transactions: list[Transaction]
    batch_size: int = 80


class EnrichTransactionsHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
    ) -> None:
        self._llm = llm

    async def __call__(self, command: EnrichTransactionsCommand) -> list[Transaction]:
        if not command.transactions:
            return list(command.transactions)

        out = list(command.transactions)
        for start in range(0, len(out), command.batch_size):
            batch = out[start : start + command.batch_size]
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
                'Return a JSON object {"items": [...]} with one item per row.\n\n'
                f"{json.dumps(records, indent=2)}"
            )
            try:
                resp = await self._llm.call_structured(
                    system=_SYSTEM,
                    user=user,
                    response_model=_EnrichResponse,
                    role=LLMRole.CHEAP,
                )
            except Exception:
                continue
            by_index = {item.index: item for item in resp.items}
            for i in range(start, min(start + command.batch_size, len(out))):
                item = by_index.get(i)
                if item is None:
                    continue
                t = out[i]
                out[i] = Transaction(
                    date=t.date,
                    description=t.description,
                    deposit=t.deposit,
                    withdrawal=t.withdrawal,
                    category=item.category,
                    vendor=item.vendor,
                    confidence=item.confidence,
                    vendor_logo=t.vendor_logo,
                    vendor_domain=t.vendor_domain,
                    vendor_canonical=t.vendor_canonical,
                )
        return out
