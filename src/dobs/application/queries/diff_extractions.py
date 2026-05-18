from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _row_key(t: dict[str, Any]) -> tuple[Any, ...]:
    side = "D" if t.get("deposit") is not None else "W"
    amount = t.get("deposit") if t.get("deposit") is not None else t.get("withdrawal")
    amount = round(float(amount or 0.0), 2)
    desc = re.sub(r"\s+", " ", (t.get("description") or "")).strip()[:60]
    return (t.get("date"), side, amount, desc)


@dataclass(frozen=True, kw_only=True, slots=True)
class DiffExtractionsQuery:
    result_a: dict[str, Any]
    result_b: dict[str, Any]


@dataclass(frozen=True, kw_only=True, slots=True)
class DiffExtractionsResult:
    only_in_a_count: int
    only_in_b_count: int
    changed_count: int
    common_count: int
    only_in_a: list[dict[str, Any]]
    only_in_b: list[dict[str, Any]]
    changed: list[dict[str, Any]]
    summary_deltas: dict[str, Any]


class DiffExtractionsHandler:
    def __init__(self, /) -> None:
        pass

    async def __call__(self, query: DiffExtractionsQuery) -> DiffExtractionsResult:
        tx_a: list[dict[str, Any]] = query.result_a.get("transactions") or []
        tx_b: list[dict[str, Any]] = query.result_b.get("transactions") or []

        by_key_a = {_row_key(t): t for t in tx_a}
        by_key_b = {_row_key(t): t for t in tx_b}

        only_a_keys = set(by_key_a) - set(by_key_b)
        only_b_keys = set(by_key_b) - set(by_key_a)
        common = set(by_key_a) & set(by_key_b)

        changed: list[dict[str, Any]] = []
        for k in common:
            ra, rb = by_key_a[k], by_key_b[k]
            cmp_fields = ("description", "category", "vendor", "confidence")
            deltas = {
                f: {"a": ra.get(f), "b": rb.get(f)} for f in cmp_fields if ra.get(f) != rb.get(f)
            }
            if deltas:
                changed.append({"key": list(k), "fields": deltas})

        def _summary_delta(sa: dict[str, Any], sb: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for key in (
                "beginning_balance",
                "ending_balance",
                "deposits_total",
                "deposits_count",
                "withdrawals_total",
                "withdrawals_count",
            ):
                av, bv = sa.get(key), sb.get(key)
                if av != bv:
                    out[key] = {
                        "a": av,
                        "b": bv,
                        "delta": (bv or 0) - (av or 0) if isinstance(av, (int, float)) else None,
                    }
            return out

        return DiffExtractionsResult(
            only_in_a_count=len(only_a_keys),
            only_in_b_count=len(only_b_keys),
            changed_count=len(changed),
            common_count=len(common),
            only_in_a=[by_key_a[k] for k in only_a_keys][:50],
            only_in_b=[by_key_b[k] for k in only_b_keys][:50],
            changed=changed[:50],
            summary_deltas=_summary_delta(
                query.result_a.get("summary") or {},
                query.result_b.get("summary") or {},
            ),
        )
