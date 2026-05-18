from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from dishka import make_async_container  # noqa: E402

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand  # noqa: E402
from dobs.main.di import _ReplayingExtractHandler, build_providers  # noqa: E402


ETALON = [
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


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


async def _amain() -> int:
    pdf = ROOT / "Binder2_Redacted.pdf"
    txt = ROOT / "ixonia_ocr.txt"

    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("EXTRACTOR_DEMO_REPLAY"):
        _stderr("ERROR: set ANTHROPIC_API_KEY or EXTRACTOR_DEMO_REPLAY=1")
        return 2

    backend_name = os.getenv("EXTRACTOR_BACKEND", "anthropic")
    _stderr(f"Backend: {backend_name}")

    container = make_async_container(*build_providers())
    command = ExtractStatementCommand(
        pdf_path=str(pdf),
        txt_path=str(txt) if txt.exists() else None,
        parallel=2,
    )
    t0 = time.time()
    try:
        async with container() as scope:
            handler = await scope.get(_ReplayingExtractHandler)
            results = await handler(command)
    finally:
        await container.close()
    elapsed = time.time() - t0
    _stderr(f"\n=== Extraction finished in {elapsed:.1f}s ({len(results)} statements) ===\n")

    out_path = ROOT / "out" / "ixonia_extraction.json"
    out_path.parent.mkdir(exist_ok=True)

    def _default(obj):
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    out_path.write_text(json.dumps(results, indent=2, default=_default), encoding="utf-8")
    _stderr(f"Wrote {out_path}")

    _stderr("\n=== Per-statement comparison vs etalon ===")
    matches = 0
    for r in results:
        account = r["account"] if isinstance(r, dict) else r.account
        summary = r["summary"] if isinstance(r, dict) else r.summary
        period_start = account["period"]["start"] if isinstance(account, dict) else account.period.start
        d = date.fromisoformat(period_start)
        period_label = d.strftime("%b %Y")
        last4 = account["account_last4"] if isinstance(account, dict) else account.account_last4
        dep_cnt = summary["deposits_count"] if isinstance(summary, dict) else summary.deposits_count
        dep_sum = summary["deposits_total"] if isinstance(summary, dict) else summary.deposits_total
        with_cnt = summary["withdrawals_count"] if isinstance(summary, dict) else summary.withdrawals_count
        etalon_match = next(
            (e for e in ETALON if e[0] == period_label and e[1] == last4),
            None,
        )
        if etalon_match:
            _, _, e_dep_cnt, e_dep_sum, e_with_cnt = etalon_match
            ok = (
                dep_cnt == e_dep_cnt
                and abs(dep_sum - e_dep_sum) < 0.01
                and with_cnt == e_with_cnt
            )
            matches += int(ok)
            _stderr(f"  {period_label} acct {last4}: {'OK' if ok else 'MISMATCH'}")
        else:
            _stderr(f"  {period_label} acct {last4}: no etalon match")

    _stderr(f"\n{matches}/{len(ETALON)} statements match etalon exactly.")
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
