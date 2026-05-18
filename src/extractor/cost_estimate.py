"""Pre-flight cost estimate.

Approximates the USD cost of an extraction before the LLM is touched,
so a CLI / UI can warn before spending real money. The numbers are
order-of-magnitude correct, not exact -- LLM output length varies.

Heuristic:
  * 1 statement = ~1 summary call (CHEAP) + 4 chunked transactions
    calls (EXTRACT) + maybe 1 repair (REPAIR) + 1 enrich (CHEAP) if
    enabled.
  * Each chunk inputs ~5 K tokens, outputs ~2 K tokens.
  * Summary inputs ~1 K, outputs ~0.3 K.
  * Enrich inputs ~3 K, outputs ~1 K per batch (1-2 batches per stmt).

Override the prices via env (see telemetry.py).
"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class CostEstimate:
    statements: int
    enrich: bool
    backend: str
    low_usd: float
    high_usd: float

    def banner(self) -> str:
        if self.backend == "ollama":
            return f"Local LLM: estimated cost $0.00 ({self.statements} statements)"
        return (
            f"Estimated cost: ${self.low_usd:.2f} - ${self.high_usd:.2f} "
            f"({self.statements} statements{', enrich ON' if self.enrich else ''})"
        )


def estimate(
    statements: int,
    *,
    enrich: bool = False,
    backend: str = "anthropic",
    chunks_per_statement: int = 4,
    avg_repair_attempts: float = 0.5,
) -> CostEstimate:
    if backend == "ollama":
        return CostEstimate(statements, enrich, backend, 0.0, 0.0)

    # Per-Mtok prices (Sonnet 4.5, Haiku 4.5). Adjust if you set the
    # PRICE_* env vars in telemetry.py.
    sonnet_in  = float(os.getenv("PRICE_SONNET_INPUT",  "3.0"))
    sonnet_out = float(os.getenv("PRICE_SONNET_OUTPUT", "15.0"))
    haiku_in   = float(os.getenv("PRICE_HAIKU_INPUT",   "1.0"))
    haiku_out  = float(os.getenv("PRICE_HAIKU_OUTPUT",  "5.0"))

    def usd(tok_in: float, tok_out: float, rate_in: float, rate_out: float) -> float:
        return tok_in * rate_in / 1e6 + tok_out * rate_out / 1e6

    per_stmt_low = 0.0
    per_stmt_high = 0.0

    # Summary call -> Haiku
    per_stmt_low  += usd(800, 250, haiku_in, haiku_out)
    per_stmt_high += usd(1500, 400, haiku_in, haiku_out)
    # Transactions chunks -> Sonnet, in parallel but billed individually
    per_stmt_low  += chunks_per_statement * usd(4000, 1500, sonnet_in, sonnet_out)
    per_stmt_high += chunks_per_statement * usd(7000, 3000, sonnet_in, sonnet_out)
    # Repair (probabilistic) -> Sonnet
    per_stmt_low  += avg_repair_attempts * usd(8000, 2000, sonnet_in, sonnet_out)
    per_stmt_high += avg_repair_attempts * usd(12000, 4000, sonnet_in, sonnet_out)
    if enrich:
        per_stmt_low  += usd(3500, 1200, haiku_in, haiku_out)
        per_stmt_high += usd(6000, 2500, haiku_in, haiku_out)

    return CostEstimate(
        statements=statements,
        enrich=enrich,
        backend=backend,
        low_usd=round(per_stmt_low * statements, 2),
        high_usd=round(per_stmt_high * statements, 2),
    )
