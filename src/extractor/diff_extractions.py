"""Compute a structured diff between two extractions of the same statement.

Use case: you tuned a prompt, re-extracted the statement, and want to
see what changed before you accept the new version as canonical.

The diff is keyed on (date, side, rounded_amount, description_first_60)
so cosmetic changes (whitespace, vendor field added later) don't
register as a difference.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import Optional


def _row_key(t: dict) -> tuple:
    side = "D" if t.get("deposit") is not None else "W"
    amount = t.get("deposit") if t.get("deposit") is not None else t.get("withdrawal")
    amount = round(float(amount or 0.0), 2)
    desc = re.sub(r"\s+", " ", (t.get("description") or "")).strip()[:60]
    return (t.get("date"), side, amount, desc)


@dataclass
class ExtractionDiff:
    only_in_a_count: int = 0
    only_in_b_count: int = 0
    changed_count: int = 0
    common_count: int = 0
    only_in_a: list[dict] = field(default_factory=list)
    only_in_b: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)
    summary_deltas: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _summary_delta(sa: dict, sb: dict) -> dict:
    out: dict = {}
    for k in (
        "beginning_balance", "ending_balance",
        "deposits_total", "deposits_count",
        "withdrawals_total", "withdrawals_count",
    ):
        av, bv = sa.get(k), sb.get(k)
        if av != bv:
            out[k] = {"a": av, "b": bv,
                      "delta": (bv or 0) - (av or 0) if isinstance(av, (int, float)) else None}
    return out


def diff_extractions(a: dict, b: dict) -> ExtractionDiff:
    """Compare two statement results (the dicts returned by extract_all).

    Conventionally `a` is the older / cached run, `b` is the new
    re-extraction. `only_in_b` reads as "added", `only_in_a` as
    "removed", `changed` as "non-key field shifted on a row that's still
    present".
    """
    tx_a: list[dict] = a.get("transactions", []) or []
    tx_b: list[dict] = b.get("transactions", []) or []

    by_key_a = {_row_key(t): t for t in tx_a}
    by_key_b = {_row_key(t): t for t in tx_b}

    only_a_keys = set(by_key_a) - set(by_key_b)
    only_b_keys = set(by_key_b) - set(by_key_a)
    common = set(by_key_a) & set(by_key_b)

    changed: list[dict] = []
    for k in common:
        ra, rb = by_key_a[k], by_key_b[k]
        # Compare the "soft" fields that DIDN'T contribute to the key.
        cmp_fields = ("description", "category", "vendor", "confidence")
        deltas = {f: {"a": ra.get(f), "b": rb.get(f)}
                  for f in cmp_fields
                  if ra.get(f) != rb.get(f)}
        if deltas:
            changed.append({"key": list(k), "fields": deltas})

    return ExtractionDiff(
        only_in_a_count=len(only_a_keys),
        only_in_b_count=len(only_b_keys),
        changed_count=len(changed),
        common_count=len(common),
        only_in_a=[by_key_a[k] for k in only_a_keys][:50],
        only_in_b=[by_key_b[k] for k in only_b_keys][:50],
        changed=changed[:50],
        summary_deltas=_summary_delta(
            a.get("summary", {}) or {}, b.get("summary", {}) or {},
        ),
    )
