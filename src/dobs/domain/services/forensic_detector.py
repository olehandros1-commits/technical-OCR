from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date
from statistics import median

from dobs.domain.value_objects.anomaly import Anomaly
from dobs.domain.value_objects.transaction import Transaction


_BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

_HOLIDAYS = {
    date(2024, 1, 1),  date(2024, 1, 15), date(2024, 2, 19),
    date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4),
    date(2024, 9, 2),  date(2024, 10, 14), date(2024, 11, 11),
    date(2024, 11, 28), date(2024, 12, 25),
    date(2025, 1, 1),  date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4),
    date(2025, 9, 1),  date(2025, 10, 13), date(2025, 11, 11),
    date(2025, 11, 27), date(2025, 12, 25),
}


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _first_digit(x: float) -> int | None:
    x = abs(x)
    if x <= 0:
        return None
    while x < 1:
        x *= 10
    return int(str(int(x))[0])


async def detect_forensic_anomalies(transactions: list[Transaction]) -> list[Anomaly]:
    out: list[Anomaly] = []
    if not transactions:
        return out

    amounts = [
        t.deposit if t.deposit is not None else (t.withdrawal or 0.0)
        for t in transactions
    ]
    digits = [d for d in (_first_digit(a) for a in amounts) if d is not None]
    if len(digits) >= 50:
        observed = Counter(digits)
        total = sum(observed.values())
        max_drift = 0.0
        worst_d = None
        for d, exp_share in _BENFORD.items():
            obs_share = observed.get(d, 0) / total
            drift = abs(obs_share - exp_share)
            if drift > max_drift:
                max_drift = drift
                worst_d = d
        if max_drift > 0.05:
            out.append(Anomaly(
                kind="size_outlier",
                severity="warn",
                transaction_index=None,
                message=(
                    f"[benford] First-digit distribution drifts {max_drift:.1%} "
                    f"from Benford expectation at digit {worst_d}. "
                    "Classic embezzlement / data-fabrication signal -- audit "
                    "recommended."
                ),
            ))

    vendor_out: dict[str, float] = defaultdict(float)
    total_out = 0.0
    for t in transactions:
        if t.withdrawal is not None and t.vendor:
            vendor_out[t.vendor] += t.withdrawal
            total_out += t.withdrawal
    if total_out > 0 and vendor_out:
        top_vendor, top_amt = max(vendor_out.items(), key=lambda kv: kv[1])
        share = top_amt / total_out
        if share > 0.35 and total_out > 10_000:
            out.append(Anomaly(
                kind="size_outlier",
                severity="info",
                transaction_index=None,
                message=(
                    f"[vendor_concentration] '{top_vendor}' accounts for "
                    f"{share:.1%} of all withdrawals (${top_amt:,.2f} / "
                    f"${total_out:,.2f}). Single-vendor dependency or "
                    "kickback risk."
                ),
            ))

    daily_counts: dict[date, int] = defaultdict(int)
    daily_indices: dict[date, list[int]] = defaultdict(list)
    for i, t in enumerate(transactions):
        d = _parse_date(t.date)
        if d:
            daily_counts[d] += 1
            daily_indices[d].append(i)
    if daily_counts:
        med = median(daily_counts.values())
        thr = max(int(med * 3), 10)
        for d, n in daily_counts.items():
            if n > thr:
                out.append(Anomaly(
                    kind="size_outlier",
                    severity="info",
                    transaction_index=daily_indices[d][0],
                    message=(
                        f"[velocity] {d.isoformat()} has {n} transactions "
                        f"(median day = {med:.0f}). Unusual burst."
                    ),
                ))

    for i, t in enumerate(transactions):
        d = _parse_date(t.date)
        if d is None:
            continue
        if d.weekday() >= 5:
            out.append(Anomaly(
                kind="size_outlier",
                severity="info",
                transaction_index=i,
                message=(
                    f"[weekend] Transaction posted on "
                    f"{d.strftime('%A %Y-%m-%d')}. Most business accounts "
                    "don't post on weekends; worth a glance."
                ),
            ))
        elif d in _HOLIDAYS:
            out.append(Anomaly(
                kind="size_outlier",
                severity="info",
                transaction_index=i,
                message=(
                    f"[holiday] Transaction posted on a US federal holiday "
                    f"({d.isoformat()}). Verify the date is correct."
                ),
            ))

    big_withdrawals = [t.withdrawal for t in transactions
                       if t.withdrawal is not None and t.withdrawal >= 1000]
    if len(big_withdrawals) >= 20:
        round_ones = sum(1 for w in big_withdrawals if abs(w - round(w)) < 0.01
                         and int(w) % 100 == 0)
        share = round_ones / len(big_withdrawals)
        if share > 0.20:
            out.append(Anomaly(
                kind="round_number_outlier",
                severity="info",
                transaction_index=None,
                message=(
                    f"[round_numbers] {share:.0%} of withdrawals over $1k "
                    f"are exact $100 multiples ({round_ones} of "
                    f"{len(big_withdrawals)}). Unusual for true B2B activity."
                ),
            ))

    return out
