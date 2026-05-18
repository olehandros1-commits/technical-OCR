from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

import aiosqlite

from dobs.application.ports.cache import StatementCachePort
from dobs.domain.entities.statement import Statement
from dobs.domain.value_objects.account import Account
from dobs.domain.value_objects.anomaly import Anomaly
from dobs.domain.value_objects.period import Period
from dobs.domain.value_objects.reconciliation import ReconciliationResult
from dobs.domain.value_objects.recurring_group import RecurringGroup
from dobs.domain.value_objects.skipped_row import SkippedRow
from dobs.domain.value_objects.summary import Summary
from dobs.domain.value_objects.transaction import Transaction


_SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    key         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reconciled  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_created ON statements(created_at);
"""


def _statement_to_json(statement: Statement) -> str:
    d = asdict(statement)
    d["oid"] = str(statement.oid)
    return json.dumps(d)


def _statement_from_dict(d: dict) -> Statement:
    account_d = d["account"]
    period_d = account_d["period"]
    account = Account(
        bank=account_d["bank"],
        account_last4=account_d["account_last4"],
        period=Period(start=period_d["start"], end=period_d["end"]),
    )
    summary_d = d["summary"]
    summary = Summary(
        beginning_balance=summary_d["beginning_balance"],
        ending_balance=summary_d["ending_balance"],
        deposits_total=summary_d["deposits_total"],
        withdrawals_total=summary_d["withdrawals_total"],
        deposits_count=summary_d.get("deposits_count"),
        withdrawals_count=summary_d.get("withdrawals_count"),
        currency=summary_d.get("currency"),
    )
    transactions = [
        Transaction(
            date=t["date"],
            description=t["description"],
            deposit=t.get("deposit"),
            withdrawal=t.get("withdrawal"),
            category=t.get("category"),
            vendor=t.get("vendor"),
            confidence=t.get("confidence"),
            vendor_logo=t.get("vendor_logo"),
            vendor_domain=t.get("vendor_domain"),
            vendor_canonical=t.get("vendor_canonical"),
        )
        for t in d.get("transactions", [])
    ]
    skipped_rows = [
        SkippedRow(raw=s["raw"], reason=s["reason"])
        for s in d.get("skipped_rows", [])
    ]
    rec_d = d.get("reconciliation")
    reconciliation: ReconciliationResult | None = None
    if rec_d is not None:
        reconciliation = ReconciliationResult(
            ok=rec_d["ok"],
            deposits_sum=rec_d["deposits_sum"],
            withdrawals_sum=rec_d["withdrawals_sum"],
            deposits_count_actual=rec_d["deposits_count_actual"],
            withdrawals_count_actual=rec_d["withdrawals_count_actual"],
            deposits_total_delta=rec_d.get("deposits_total_delta", 0.0),
            withdrawals_total_delta=rec_d.get("withdrawals_total_delta", 0.0),
            deposits_count_delta=rec_d.get("deposits_count_delta", 0),
            withdrawals_count_delta=rec_d.get("withdrawals_count_delta", 0),
            balance_equation_delta=rec_d.get("balance_equation_delta", 0.0),
            issues=tuple(rec_d.get("issues", ())),
        )
    anomalies = [
        Anomaly(
            kind=a["kind"],
            severity=a["severity"],
            message=a["message"],
            transaction_index=a.get("transaction_index"),
            related_index=a.get("related_index"),
        )
        for a in d.get("anomalies", [])
    ]
    recurring = [
        RecurringGroup(
            vendor_key=r["vendor_key"],
            side=r["side"],
            avg_amount=r["avg_amount"],
            cadence_days=r["cadence_days"],
            cadence_label=r["cadence_label"],
            occurrences=tuple(r.get("occurrences", ())),
            next_predicted_date=r.get("next_predicted_date"),
        )
        for r in d.get("recurring", [])
    ]
    return Statement(
        oid=UUID(d["oid"]),
        account=account,
        summary=summary,
        transactions=transactions,
        skipped_rows=skipped_rows,
        reconciliation=reconciliation,
        anomalies=anomalies,
        recurring=recurring,
    )


class SqliteStatementCache(StatementCachePort):
    def __init__(self, /, *, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialised = False

    async def _ensure_init(self) -> None:
        if self._initialised:
            return
        async with self._init_lock:
            if self._initialised:
                return
            async with aiosqlite.connect(self._db_path) as db:
                await db.executescript(_SCHEMA)
                await db.commit()
            self._initialised = True

    async def get(self, key: str) -> Statement | None:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT payload FROM statements WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return _statement_from_dict(json.loads(row[0]))

    async def put(self, key: str, statement: Statement) -> None:
        await self._ensure_init()
        payload = _statement_to_json(statement)
        reconciled = int(statement.reconciliation.ok if statement.reconciliation else 0)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO statements (key, payload, reconciled) "
                "VALUES (?, ?, ?)",
                (key, payload, reconciled),
            )
            await db.commit()

    async def delete(self, key: str) -> bool:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM statements WHERE key = ?", (key,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def clear(self) -> int:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM statements")
            await db.commit()
            return cursor.rowcount

    async def keys(self, limit: int = 200) -> list[dict]:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT key, created_at, reconciled FROM statements "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [{"key": k, "created_at": c, "reconciled": bool(r)} for k, c, r in rows]

    async def stats(self) -> dict:
        await self._ensure_init()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM statements") as cursor:
                total = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM statements WHERE reconciled = 1"
            ) as cursor:
                ok = (await cursor.fetchone())[0]
        return {"total": total, "reconciled": ok}
