from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median

from dobs.domain.value_objects.anomaly import Anomaly
from dobs.domain.value_objects.transaction import Transaction


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


async def detect_anomalies(
    transactions: list[Transaction],
    period_start: str,
    period_end: str,
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    if not transactions:
        return anomalies

    start = _parse_date(period_start)
    end = _parse_date(period_end)

    if start and end:
        for i, t in enumerate(transactions):
            d = _parse_date(t.date)
            if d and (d < start or d > end):
                anomalies.append(Anomaly(
                    kind="date_out_of_period",
                    severity="warn",
                    transaction_index=i,
                    message=(
                        f"Transaction dated {t.date} is outside the statement "
                        f"period {period_start} - {period_end}."
                    ),
                ))

    key_to_indices: dict[tuple, list[int]] = defaultdict(list)
    for i, t in enumerate(transactions):
        side = "D" if t.deposit is not None else "W"
        amount = t.deposit if t.deposit is not None else t.withdrawal
        if amount is None:
            continue
        key_to_indices[(t.date, side, round(amount, 2))].append(i)
    for key, indices in key_to_indices.items():
        if len(indices) >= 2:
            for i in indices[1:]:
                anomalies.append(Anomaly(
                    kind="duplicate_pair",
                    severity="info",
                    transaction_index=i,
                    related_index=indices[0],
                    message=(
                        f"Row {i} has the same date/amount/side as row "
                        f"{indices[0]} ({key[0]}, {key[1]}, ${key[2]:.2f})."
                    ),
                ))

    amounts = [
        t.deposit if t.deposit is not None else (t.withdrawal or 0.0)
        for t in transactions
    ]
    non_zero = [a for a in amounts if a > 0]
    if non_zero:
        med = median(non_zero)
        threshold = med * 20
        for i, a in enumerate(amounts):
            if a > threshold and a > 50000:
                anomalies.append(Anomaly(
                    kind="size_outlier",
                    severity="info",
                    transaction_index=i,
                    message=(
                        f"Amount ${a:,.2f} is more than 20x the median "
                        f"transaction (${med:,.2f}). Worth a sanity check."
                    ),
                ))

    for i, t in enumerate(transactions):
        if t.confidence is not None and t.confidence < 0.5:
            anomalies.append(Anomaly(
                kind="low_confidence",
                severity="warn",
                transaction_index=i,
                message=(
                    f"Model confidence {t.confidence:.2f} -- worth manual "
                    "review (often means redacted/wrapped description)."
                ),
            ))

    return anomalies
