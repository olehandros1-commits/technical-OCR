from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from dobs.domain.entities.base import Entity
from dobs.domain.value_objects.account import Account
from dobs.domain.value_objects.anomaly import Anomaly
from dobs.domain.value_objects.reconciliation import ReconciliationResult
from dobs.domain.value_objects.recurring_group import RecurringGroup
from dobs.domain.value_objects.skipped_row import SkippedRow
from dobs.domain.value_objects.summary import Summary
from dobs.domain.value_objects.transaction import Transaction


@dataclass(eq=False, kw_only=True)
class Statement(Entity[UUID]):
    account: Account
    summary: Summary
    transactions: list[Transaction] = field(default_factory=list)
    skipped_rows: list[SkippedRow] = field(default_factory=list)
    reconciliation: ReconciliationResult | None = None
    anomalies: list[Anomaly] = field(default_factory=list)
    recurring: list[RecurringGroup] = field(default_factory=list)
