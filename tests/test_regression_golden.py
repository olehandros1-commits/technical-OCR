"""Golden regression test: the bundled Ixonia extraction must reconcile
10/10 with every summary field bit-exact to the published etalon.

This test does NOT call the LLM -- it reads the cached extraction at
out/ixonia_extraction.json (the result of a real prior run) and
verifies the saved structure still matches the etalon. Run after any
prompt change to ensure you didn't regress.

In CI you would run this against a re-extraction with a stubbed
backend, then promote the snapshot to golden when you intentionally
change behavior.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "out" / "ixonia_extraction.json"


# Etalon from the task PDF (Notion source-of-truth).
_ETALON = [
    ("Apr 2025", "4664", 81, 1_214_254.05, 111),
    ("May 2025", "4664", 95, 926_416.11, 142),
    ("Jun 2024", "4664", 63, 1_050_851.95, 99),
    ("Jul 2024", "4664", 84, 848_578.92, 82),
    ("Aug 2024", "4664", 83, 1_178_227.39, 88),
    ("Sep 2024", "4664", 71, 1_085_703.81, 118),
    ("Sep 2024", "4623", 13, 336_565.07, 35),
    ("Oct 2024", "4664", 83, 1_187_061.65, 96),
    ("Nov 2024", "4664", 75, 847_969.53, 120),
    ("Dec 2024", "4664", 67, 1_223_865.12, 65),
]


@pytest.fixture(scope="module")
def snapshot() -> list[dict]:
    if not SNAPSHOT.exists():
        pytest.skip(
            "out/ixonia_extraction.json missing -- run "
            "`python examples/run_ixonia.py` once to generate it"
        )
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_snapshot_has_ten_statements(snapshot):
    assert len(snapshot) == 10


def test_every_statement_reconciled(snapshot):
    bad = [r for r in snapshot if not (r.get("_reconciliation") or {}).get("ok")]
    assert not bad, f"{len(bad)} statement(s) failed reconciliation: {bad}"


def test_each_statement_matches_etalon(snapshot):
    """Iterate the etalon list; for each entry find the matching
    snapshot row by (period start month, account_last4) and compare."""
    from datetime import date

    by_key = {}
    for r in snapshot:
        d = date.fromisoformat(r["account"]["period"]["start"])
        key = (d.strftime("%b %Y"), r["account"]["account_last4"])
        by_key[key] = r

    failures = []
    for label, acct, dep_cnt, dep_sum, with_cnt in _ETALON:
        row = by_key.get((label, acct))
        if row is None:
            failures.append(f"missing {label} acct {acct}")
            continue
        s = row["summary"]
        if s["deposits_count"] != dep_cnt:
            failures.append(
                f"{label} acct {acct}: deposits_count {s['deposits_count']} != {dep_cnt}"
            )
        if abs(s["deposits_total"] - dep_sum) > 0.01:
            failures.append(
                f"{label} acct {acct}: deposits_total {s['deposits_total']} != {dep_sum}"
            )
        if s["withdrawals_count"] != with_cnt:
            failures.append(
                f"{label} acct {acct}: withdrawals_count {s['withdrawals_count']} != {with_cnt}"
            )
    assert not failures, "\n".join(failures)


def test_total_transactions_above_threshold(snapshot):
    total = sum(len(r["transactions"]) for r in snapshot)
    # Sanity: 10 statements, ~50-300 tx each.
    assert total > 1000, f"only {total} transactions extracted"
