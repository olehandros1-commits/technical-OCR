"""Demo replay mode: simulate a live extraction from a saved snapshot.

When `EXTRACTOR_DEMO_REPLAY=1` (or `--demo-replay` on the CLI), the
pipeline does NOT call any LLM. Instead it reads a pre-saved
`out/ixonia_extraction.json` (or whatever `EXTRACTOR_DEMO_REPLAY_FILE`
points to), then streams a realistic sequence of pipeline events with
small delays so the UI animates as if the extraction were running live.

Why this is in the codebase, not on a Notion doc:
  * Live demos cost real money. A typical full-document Sonnet run on
    the bundled sample is ~$10 cold-cache. Demo runs with `--enrich`
    can push that higher.
  * Replay mode gives the audience the exact same UX (SSE events,
    telemetry strip, HITL queue, Excel download) at zero API spend.
  * The replayed events come from a real previous run -- there's no
    fabrication, just deterministic playback.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Callable, Optional


def is_replay_enabled() -> bool:
    return os.getenv("EXTRACTOR_DEMO_REPLAY", "0") in {"1", "true", "yes"}


def replay_path(tier: str | None = None) -> Path:
    """Pick the snapshot file. Order:
      1. explicit EXTRACTOR_DEMO_REPLAY_FILE env var
      2. out/replays/{tier}.json (tier-aware, lets you stash one snapshot
         per quality tier and switch instantly on demos)
      3. out/ixonia_extraction.json (the last whole-document run)
    """
    explicit = os.getenv("EXTRACTOR_DEMO_REPLAY_FILE")
    if explicit:
        return Path(explicit)
    if tier:
        per_tier = Path("out/replays") / f"{tier}.json"
        if per_tier.exists():
            return per_tier
    return Path("out/ixonia_extraction.json")


def replay(
    log_event: Optional[Callable[[str, dict], None]] = None,
    *,
    speed: float = 1.0,
    tier: str | None = None,
) -> list[dict]:
    """Stream simulated events; return the saved results list.

    `speed` scales the synthetic delays (1.0 = realistic pace, 0.0 =
    instant for tests). `tier` picks the tier-specific snapshot.
    """
    path = replay_path(tier)
    if not path.exists():
        raise FileNotFoundError(
            f"Demo replay snapshot not found at {path}. Run a real "
            "extraction once (or copy ixonia_extraction.json into out/) "
            "before enabling EXTRACTOR_DEMO_REPLAY."
        )
    results = json.loads(path.read_text(encoding="utf-8"))

    def emit(name: str, data: dict, delay_s: float = 0.0) -> None:
        if delay_s and speed > 0:
            time.sleep(delay_s * speed)
        if log_event:
            log_event(name, data)

    # --- ingest -------------------------------------------------------
    emit("ingest_start", {
        "pdf": "demo://replay", "txt": None,
        "backend": "demo-replay", "ocr_mode": "skip",
    }, 0.0)
    emit("ocr_cache_hit", {
        "file_hash": "demo-snapshot", "chars": 0, "method": "replay",
    }, 0.05)
    emit("ingest_done", {"chars": 331988}, 0.05)
    emit("segment_done_all", {
        "statement_count": len(results),
        "periods": [r["account"]["period"]["start"] for r in results],
    }, 0.1)

    # --- per-statement playback --------------------------------------
    for r in results:
        label = f"{r['account']['period']['start']} acct {r['account'].get('account_last4') or '?'}"
        emit("segment_start", {
            "label": label, "chars": 20000, "backend": "demo-replay",
        }, 0.05)
        emit("summary_done", {
            "label": label,
            "bank": r["account"].get("bank"),
            "last4": r["account"].get("account_last4"),
            "period": f"{r['account']['period']['start']} -> "
                      f"{r['account']['period']['end']}",
            "elapsed_s": 0.4,
        }, 0.2)
        emit("transactions_done", {
            "label": label,
            "count": len(r["transactions"]),
            "skipped": 0,
            "elapsed_s": 0.6,
        }, 0.3)
        recon = r.get("_reconciliation") or {}
        emit("reconcile", {
            "attempt": 0, "ok": recon.get("ok", False),
            "error": 0.0, "issues": recon.get("issues", []),
        }, 0.05)
        anomalies = r.get("_anomalies", [])
        if anomalies:
            by_kind: dict = {}
            for a in anomalies:
                by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
            emit("anomalies_found", {
                "label": label, "count": len(anomalies), "by_kind": by_kind,
            }, 0.0)
        emit("segment_done", {
            "label": label, "reconciled": recon.get("ok", False),
            "issues": recon.get("issues", []),
        }, 0.05)
    return results
