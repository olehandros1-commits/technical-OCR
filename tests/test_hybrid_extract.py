import json

from dobs.application.commands.extraction.extract_transactions_hybrid import (
    ExtractTransactionsHybridCommand,
    ExtractTransactionsHybridHandler,
    _ValidatorResponse,
    _ValidatedRow,
)
from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.services.prompt_sanitizer import PromptSanitizer
from dobs.domain.services.row_parser import RowParser
from dobs.domain.value_objects.llm_role import LLMRole


class _MockValidator:
    name = "mock-validator"

    def __init__(self) -> None:
        self.calls = 0
        self.last_user: str = ""

    async def call_structured(self, *, system, user, response_model, role=LLMRole.CHEAP, **kw):
        self.calls += 1
        self.last_user = user
        start = user.index("[")
        records = json.loads(user[start:])
        rows = []
        for rec in records:
            desc_upper = rec["desc"].upper()
            is_withdrawal = any(t in desc_upper for t in
                                ("CHECK", "PAYABLE", "WITHDRAW", "PMT"))
            amount = rec["amounts"][0] if rec["amounts"] else 0.0
            rows.append(_ValidatedRow(
                index=rec["index"],
                keep=True,
                side="withdrawal" if is_withdrawal else "deposit",
                date=rec["date"],
                description=rec["desc"],
                amount=amount,
            ))
        return _ValidatorResponse(rows=rows)

    async def call_vision(self, **kw):
        raise NotImplementedError

    def supports_vision(self) -> bool:
        return False


_SAMPLE = (
    "Apr 01 AIRLINEHYD 2759/VENDOR PMT 1,809.28 598,877.98 "
    "Apr 01 METAL TRADERS IN/ACH 3,506.80 602,384.78 "
    "Apr 03 PAYABLES 1452496195 10.90 597,069.70 "
    "Apr 15 CHECK #40788 500.00 595,069.70"
)


async def test_hybrid_lifts_rows_via_regex_and_classifies_via_llm():
    backend = _MockValidator()
    handler = ExtractTransactionsHybridHandler(
        llm=backend, sanitizer=PromptSanitizer(), row_parser=RowParser(),
    )
    result = await handler(ExtractTransactionsHybridCommand(
        segment_text=_SAMPLE,
        period_start="2025-04-01",
        period_end="2025-04-30",
    ))
    assert backend.calls == 1
    assert len(result.transactions) == 4
    sides = [("D" if t.deposit is not None else "W") for t in result.transactions]
    assert sides == ["W", "D", "W", "W"]


async def test_hybrid_user_payload_is_compact_json():
    backend = _MockValidator()
    handler = ExtractTransactionsHybridHandler(
        llm=backend, sanitizer=PromptSanitizer(), row_parser=RowParser(),
    )
    await handler(ExtractTransactionsHybridCommand(
        segment_text=_SAMPLE,
        period_start="2025-04-01",
        period_end="2025-04-30",
    ))
    for tok in ("index", "date", "desc", "amounts", "is_check"):
        assert tok in backend.last_user
    assert "MISCELLANEOUS DEBITS" not in backend.last_user


async def test_hybrid_falls_back_when_regex_finds_nothing():
    from dobs.application.commands.extraction.extract_transactions_hybrid import _TransactionsResult

    class _FallbackBackend:
        name = "fallback"
        calls = 0

        async def call_structured(self, **kw):
            self.__class__.calls = getattr(self.__class__, "calls", 0) + 1
            return _TransactionsResult(transactions=[], skipped_rows=[])

        async def call_vision(self, **kw):
            raise NotImplementedError

        def supports_vision(self):
            return False

    backend = _FallbackBackend()
    handler = ExtractTransactionsHybridHandler(
        llm=backend, sanitizer=PromptSanitizer(), row_parser=RowParser(),
    )
    result = await handler(ExtractTransactionsHybridCommand(
        segment_text="no dates here",
        period_start="2025-04-01",
        period_end="2025-04-30",
    ))
    assert result.transactions == []
