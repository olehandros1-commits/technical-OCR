"""Demo script: run the extractor against the bundled Ixonia sample and
print a per-statement comparison against the published etalon table.

Usage (from project root):
    python examples/run_ixonia.py
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from extractor.pipeline import extract_all  # noqa: E402

# Etalon from the task PDF -- ground truth for the 10 statements.
ETALON = [
    # (period_label, account_last4, deposits_count, deposits_total, withdrawals_count)
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


def _log_event(name: str, data: dict) -> None:
    _stderr(f"[{name}] {data}")


def main() -> int:
    pdf = ROOT / "Binder2_Redacted.pdf"
    txt = ROOT / "ixonia_ocr.txt"

    if not os.getenv("ANTHROPIC_API_KEY"):
        _stderr("ERROR: ANTHROPIC_API_KEY not set. See .env.example.")
        return 2

    backend_name = os.getenv("EXTRACTOR_BACKEND", "anthropic")
    _stderr(f"Backend: {backend_name}")
    t0 = time.time()
    results = extract_all(
        str(pdf),
        str(txt) if txt.exists() else None,
        backend=backend_name,
        parallel=2,
        log_event=_log_event,
    )
    elapsed = time.time() - t0
    _stderr(f"\n=== Extraction finished in {elapsed:.1f}s ({len(results)} statements) ===\n")

    out_path = ROOT / "out" / "ixonia_extraction.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    _stderr(f"Wrote {out_path}")

    _stderr("\n=== Per-statement comparison vs etalon ===")
    _stderr(
        f"{'Period':<10} {'Acct':<5} {'Dep#':>5} {'DepExp':>6} "
        f"{'Dep$':>14} {'DepExp$':>14} {'With#':>6} {'WithExp':>7} {'OK?'}"
    )
    matches = 0
    for r in results:
        period_start = r["account"]["period"]["start"]
        # Map to month label like "Apr 2025"
        from datetime import date
        d = date.fromisoformat(period_start)
        period_label = d.strftime("%b %Y")
        last4 = r["account"]["account_last4"]
        dep_cnt = r["summary"]["deposits_count"]
        dep_sum = r["summary"]["deposits_total"]
        with_cnt = r["summary"]["withdrawals_count"]
        # Find matching etalon row
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
            _stderr(
                f"{period_label:<10} {last4:<5} {dep_cnt!s:>5} {e_dep_cnt!s:>6} "
                f"{dep_sum:>14,.2f} {e_dep_sum:>14,.2f} "
                f"{with_cnt!s:>6} {e_with_cnt!s:>7}  "
                f"{'YES' if ok else 'NO'}"
            )
        else:
            _stderr(
                f"{period_label:<10} {last4:<5} {dep_cnt!s:>5} {'?':>6} "
                f"{dep_sum:>14,.2f} {'?':>14} "
                f"{with_cnt!s:>6} {'?':>7}  (no etalon match)"
            )
    _stderr(
        f"\n{matches}/{len(ETALON)} statements match etalon exactly "
        f"(account+counts+deposits_total)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
