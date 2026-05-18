from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def is_replay_enabled() -> bool:
    return os.getenv("EXTRACTOR_DEMO_REPLAY", "0") in {"1", "true", "yes"}


def replay_path(tier: str | None = None) -> Path:
    explicit = os.getenv("EXTRACTOR_DEMO_REPLAY_FILE")
    if explicit:
        return Path(explicit)
    if tier:
        per_tier = Path("out/replays") / f"{tier}.json"
        if per_tier.exists():
            return per_tier
    return Path("out/ixonia_extraction.json")


class DemoReplayPlayer:
    def __init__(self, /) -> None:
        pass

    async def replay(
        self,
        log_event: Callable[[str, dict[str, Any]], None] | None = None,
        *,
        speed: float = 1.0,
        tier: str | None = None,
    ) -> list[dict[str, Any]]:
        path = replay_path(tier)
        if not path.exists():
            raise FileNotFoundError(
                f"Demo replay snapshot not found at {path}. Run a real "
                "extraction once (or copy ixonia_extraction.json into out/) "
                "before enabling EXTRACTOR_DEMO_REPLAY."
            )
        results: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))

        async def emit(name: str, data: dict[str, Any], delay_s: float = 0.0) -> None:
            if delay_s and speed > 0:
                await asyncio.sleep(delay_s * speed)
            if log_event:
                log_event(name, data)

        await emit(
            "ingest_start",
            {
                "pdf": "demo://replay",
                "txt": None,
                "backend": "demo-replay",
                "ocr_mode": "skip",
            },
            0.0,
        )
        await emit(
            "ocr_cache_hit",
            {
                "file_hash": "demo-snapshot",
                "chars": 0,
                "method": "replay",
            },
            0.05,
        )
        await emit("ingest_done", {"chars": 331988}, 0.05)
        await emit(
            "segment_done_all",
            {
                "statement_count": len(results),
                "periods": [r["account"]["period"]["start"] for r in results],
            },
            0.1,
        )

        for r in results:
            label = (
                f"{r['account']['period']['start']} acct {r['account'].get('account_last4') or '?'}"
            )
            await emit(
                "segment_start",
                {
                    "label": label,
                    "chars": 20000,
                    "backend": "demo-replay",
                },
                0.05,
            )
            await emit(
                "summary_done",
                {
                    "label": label,
                    "bank": r["account"].get("bank"),
                    "last4": r["account"].get("account_last4"),
                    "period": (
                        f"{r['account']['period']['start']} -> {r['account']['period']['end']}"
                    ),
                    "elapsed_s": 0.4,
                },
                0.2,
            )
            await emit(
                "transactions_done",
                {
                    "label": label,
                    "count": len(r["transactions"]),
                    "skipped": 0,
                    "elapsed_s": 0.6,
                },
                0.3,
            )
            recon = r.get("_reconciliation") or {}
            await emit(
                "reconcile",
                {
                    "attempt": 0,
                    "ok": recon.get("ok", False),
                    "error": 0.0,
                    "issues": recon.get("issues", []),
                },
                0.05,
            )
            anomalies = r.get("_anomalies", [])
            if anomalies:
                by_kind: dict[str, int] = {}
                for a in anomalies:
                    by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + 1
                await emit(
                    "anomalies_found",
                    {
                        "label": label,
                        "count": len(anomalies),
                        "by_kind": by_kind,
                    },
                    0.0,
                )
            await emit(
                "segment_done",
                {
                    "label": label,
                    "reconciled": recon.get("ok", False),
                    "issues": recon.get("issues", []),
                },
                0.05,
            )

        return results
