"""End-to-end API smoke tests using FastAPI's TestClient.

These hit the live ASGI app without spawning uvicorn -- much faster
than the prior subprocess approach and they catch the kinds of bugs
we hit in production (silent SSE drops, tier-vs-replay precedence,
missing fields in response).

The tests are designed to run in DEMO_REPLAY mode so they never spend
on the Anthropic API and they finish in seconds.
"""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    # Force replay mode so the test doesn't depend on a real Anthropic
    # key (and never spends money). The replay snapshot is committed
    # to the repo at out/ixonia_extraction.json.
    os.environ["EXTRACTOR_DEMO_REPLAY"] = "1"
    # Pop any cached collector singletons so each test starts clean.
    from extractor.api import app
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_tiers_catalog(client):
    r = client.get("/tiers")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tiers"]]
    assert set(names) == {"premium", "balanced", "cheap", "local"}


def test_extract_replay_returns_full_payload(client):
    """The bug we just hit: user picks tier=local in UI, hits Extract,
    server should still serve the replay snapshot in seconds (not hang
    on Ollama). This test locks the precedence: REPLAY > TIER."""
    pdf_path = Path(__file__).resolve().parent.parent / "Binder2_Redacted.pdf"
    if not pdf_path.exists():
        pytest.skip("Binder2_Redacted.pdf not present in repo root")

    with pdf_path.open("rb") as f:
        r = client.post(
            "/extract",
            files={"pdf": (pdf_path.name, f, "application/pdf")},
            data={
                "tier": "local",        # the offending input
                "enrich": "false",
                "parallel": "1",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    results = body["results"]
    assert len(results) == 10
    # Replay payload must carry the enriched fields the UI renders.
    total_anom = sum(len(r.get("_anomalies", [])) for r in results)
    assert total_anom > 0, "_anomalies must be populated"
    ok = sum(1 for r in results if (r.get("_reconciliation") or {}).get("ok"))
    assert ok == 10
    # Telemetry: no LLM calls in replay mode.
    assert body["telemetry"]["total_calls"] == 0


def test_audit_log_records_extract(client):
    r = client.get("/audit?limit=5")
    assert r.status_code == 200
    rows = r.json()["records"]
    # The previous test wrote a row; we should see at least one entry.
    assert len(rows) >= 1
    latest = rows[0]
    assert latest["statement_count"] == 10
    assert latest["reconciled_count"] == 10


def test_cache_keys_endpoint(client):
    r = client.get("/cache/keys?limit=20")
    assert r.status_code == 200
    body = r.json()
    assert "keys" in body  # may be empty in replay-only environments


def test_diff_endpoint_roundtrip(client):
    """The diff endpoint should compute structured diffs cleanly even
    when the two inputs are identical (regression: this used to throw
    on empty diffs)."""
    stmt = {
        "account": {"period": {"start": "2025-04-01", "end": "2025-04-30"},
                    "account_last4": "4664"},
        "summary": {
            "beginning_balance": 100, "ending_balance": 100,
            "deposits_total": 0, "deposits_count": 0,
            "withdrawals_total": 0, "withdrawals_count": 0,
        },
        "transactions": [],
    }
    r = client.post("/diff", json={"a": stmt, "b": stmt})
    assert r.status_code == 200
    body = r.json()
    assert body["only_in_a_count"] == 0
    assert body["only_in_b_count"] == 0
    assert body["changed_count"] == 0


def test_sse_replay_completes_with_done_event(client):
    """Locks in the streaming contract: a replay job must emit a
    terminating 'done' event over /jobs/{id}/events; if it doesn't,
    the UI shows the dreaded 'Lost connection to job stream' banner.
    """
    pdf_path = Path(__file__).resolve().parent.parent / "Binder2_Redacted.pdf"
    if not pdf_path.exists():
        pytest.skip("Binder2_Redacted.pdf not present in repo root")

    with pdf_path.open("rb") as f:
        r = client.post(
            "/jobs",
            files={"pdf": (pdf_path.name, f, "application/pdf")},
            data={"tier": "local", "parallel": "1"},
        )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Read the SSE stream until we hit the terminating 'done'. The
    # whole replay should finish in well under 30 seconds.
    seen = []
    with client.stream("GET", f"/jobs/{job_id}/events") as resp:
        assert resp.status_code == 200
        for raw in resp.iter_lines():
            if not raw or not raw.startswith("data:"):
                continue
            payload = json.loads(raw[5:].strip())
            seen.append(payload["event"])
            if payload["event"] == "done":
                break
    assert seen, "no events received"
    assert seen[-1] == "done", f"stream ended without 'done': last={seen[-3:]}"
    # Replay should emit at minimum these key events.
    for required in ("tier_active", "demo_replay_active",
                     "ingest_start", "segment_done_all", "done"):
        assert required in seen, f"missing event {required}"
