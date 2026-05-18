from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AnomalyKind = Literal[
    "duplicate_pair",
    "date_out_of_period",
    "running_balance_drift",
    "round_number_outlier",
    "size_outlier",
    "low_confidence",
]

Severity = Literal["info", "warn", "error"]


@dataclass(frozen=True, kw_only=True, slots=True)
class Anomaly:
    kind: AnomalyKind
    severity: Severity
    message: str
    transaction_index: int | None = None
    related_index: int | None = None
