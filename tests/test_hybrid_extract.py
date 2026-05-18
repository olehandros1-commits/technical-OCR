"""Integration test for hybrid extraction: regex pre-parse + LLM validator."""
from pydantic import BaseModel

from extractor.backends.base import LLMBackend, LLMRole
from extractor.extract_transactions_hybrid import (
    extract_transactions_hybrid, _ValidatorResponse, _ValidatedRow,
)


class _MockValidator(LLMBackend):
    """Mock backend that returns one ValidatedRow per input candidate.

    Side-determination heuristic: descriptions containing 'CHECK',
    'PAYABLE', 'WITHDRAWAL', 'PMT' -> withdrawal; everything else -> deposit.
    """
    name = "mock-validator"

    def __init__(self) -> None:
        self.calls = 0
        self.last_user: str = ""

    def call_structured(self, system, user, response_model, *, role=LLMRole.CHEAP, **kw):
        import json
        self.calls += 1
        self.last_user = user
        # Extract the input records by parsing the user prompt.
        # In a real test we'd be more careful; here we trust the format.
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


_SAMPLE = (
    "Apr 01 AIRLINEHYD 2759/VENDOR PMT 1,809.28 598,877.98 "
    "Apr 01 METAL TRADERS IN/ACH 3,506.80 602,384.78 "
    "Apr 03 PAYABLES 1452496195 10.90 597,069.70 "
    "Apr 15 CHECK #40788 500.00 595,069.70"
)


def test_hybrid_lifts_rows_via_regex_and_classifies_via_llm():
    backend = _MockValidator()
    resp = extract_transactions_hybrid(
        _SAMPLE, "2025-04-01", "2025-04-30", backend,
    )
    assert backend.calls == 1
    # Mock returns one ValidatedRow per regex candidate (4).
    assert len(resp.transactions) == 4
    # Withdrawal classifications by mock heuristic.
    sides = [("D" if t.deposit is not None else "W") for t in resp.transactions]
    assert sides == ["W", "D", "W", "W"]  # PMT, none, PAYABLES, CHECK


def test_hybrid_user_payload_is_compact_json():
    backend = _MockValidator()
    extract_transactions_hybrid(_SAMPLE, "2025-04-01", "2025-04-30", backend)
    # Compact JSON keys we expect to see in the validator prompt.
    for tok in ("index", "date", "desc", "amounts", "is_check"):
        assert tok in backend.last_user
    # Validator should NOT have the system prompt boilerplate from the
    # main TRANSACTIONS_SYSTEM (those rules are now redundant).
    assert "MISCELLANEOUS DEBITS" not in backend.last_user


def test_hybrid_falls_back_when_regex_finds_nothing():
    # Empty text -> no regex rows -> fall back path. The mock validator
    # would NOT be called because fallback is _single_call() which uses
    # the regular TRANSACTIONS_SYSTEM. We simulate by checking that no
    # call was made when fallback is disabled.
    backend = _MockValidator()
    resp = extract_transactions_hybrid(
        "no dates here", "2025-04-01", "2025-04-30", backend,
        fallback_on_empty=False,
    )
    assert backend.calls == 0
    assert resp.transactions == []
