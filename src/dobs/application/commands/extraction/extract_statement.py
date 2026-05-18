from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from dobs.application.commands.extraction.enrich_transactions import (
    EnrichTransactionsCommand,
    EnrichTransactionsHandler,
)
from dobs.application.commands.extraction.extract_summary import (
    ExtractSummaryCommand,
    ExtractSummaryHandler,
)
from dobs.application.commands.extraction.extract_transactions import (
    ExtractTransactionsCommand,
    ExtractTransactionsHandler,
)
from dobs.application.commands.extraction.repair_statement import (
    RepairStatementCommand,
    RepairStatementHandler,
)
from dobs.application.ports.audit_sink import AuditSinkPort
from dobs.application.ports.cache import StatementCachePort
from dobs.application.ports.event_bus import EventBusPort
from dobs.application.ports.lessons_store import LessonsStorePort
from dobs.application.ports.ocr_engine import OcrEnginePort
from dobs.application.ports.telemetry_collector import TelemetryCollectorPort
from dobs.application.ports.vendor_lookup import VendorLookupPort
from dobs.application.services.segmenter import StatementSegment, StatementSegmenter
from dobs.application.services.lessons_helpers import LessonsHelper
from dobs.domain.entities.audit_record import AuditRecord
from dobs.domain.entities.statement import Statement
from dobs.domain.services.anomaly_detector import AnomalyDetector
from dobs.domain.services.continuity_auditor import ContinuityAuditor
from dobs.domain.services.forensic_detector import ForensicAnomalyDetector
from dobs.domain.services.reconcile import Reconciler
from dobs.domain.services.recurring_detector import RecurringDetector
from dobs.application.ports.llm_backend import LLMBackendPort


def _cache_key(seg: StatementSegment, backend_name: str, tenant: str) -> str:
    h = hashlib.sha256(
        f"{backend_name}|{seg.text}".encode("utf-8")
    ).hexdigest()[:16]
    return (
        f"{tenant}::"
        f"{seg.period_start_raw.replace('/', '-')}_"
        f"{seg.account_hint or 'none'}_{backend_name}_{h}"
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class ExtractStatementCommand:
    pdf_path: str | None = None
    txt_path: str | None = None
    tier: str | None = None
    ocr_mode: str = "auto"
    enrich: bool = False
    parallel: int = 2
    tenant: str = "_default"


class ExtractStatementHandler:
    def __init__(
        self,
        /,
        *,
        ocr: OcrEnginePort,
        cache: StatementCachePort,
        audit: AuditSinkPort,
        lessons: LessonsStorePort,
        event_bus: EventBusPort,
        telemetry: TelemetryCollectorPort,
        summary: ExtractSummaryHandler,
        transactions: ExtractTransactionsHandler,
        repair: RepairStatementHandler,
        enrich_cmd: EnrichTransactionsHandler,
        vendor: VendorLookupPort,
        llm: LLMBackendPort,
        segmenter: StatementSegmenter,
        reconciler: Reconciler,
        anomaly_detector: AnomalyDetector,
        continuity_auditor: ContinuityAuditor,
        forensic_detector: ForensicAnomalyDetector,
        recurring_detector: RecurringDetector,
        lessons_helper: LessonsHelper,
    ) -> None:
        self._ocr = ocr
        self._cache = cache
        self._audit = audit
        self._lessons = lessons
        self._event_bus = event_bus
        self._telemetry = telemetry
        self._summary = summary
        self._transactions = transactions
        self._repair = repair
        self._enrich_cmd = enrich_cmd
        self._vendor = vendor
        self._llm = llm
        self._segmenter = segmenter
        self._reconciler = reconciler
        self._anomaly_detector = anomaly_detector
        self._continuity_auditor = continuity_auditor
        self._forensic_detector = forensic_detector
        self._recurring_detector = recurring_detector
        self._lessons_helper = lessons_helper

    async def _process_segment(
        self,
        seg: StatementSegment,
        command: ExtractStatementCommand,
        sem: asyncio.Semaphore,
    ) -> Statement | None:
        async with sem:
            return await self._process_segment_inner(seg, command)

    async def _process_segment_inner(
        self,
        seg: StatementSegment,
        command: ExtractStatementCommand,
    ) -> Statement | None:
        label = f"{seg.period_start_raw} acct {seg.account_hint or '?'}"
        backend_name = getattr(self._llm, "name", "unknown")
        cache_key = _cache_key(seg, backend_name, command.tenant)

        cached = await self._cache.get(cache_key)
        if cached is not None:
            await self._event_bus.emit("cache_hit", {
                "label": label, "backend": backend_name, "key": cache_key
            })
            return cached

        await self._event_bus.emit("segment_start", {
            "label": label, "chars": len(seg.text), "backend": backend_name
        })

        account, summary_vo = await self._summary(
            ExtractSummaryCommand(segment_text=seg.text)
        )
        await self._event_bus.emit("summary_done", {
            "label": label,
            "bank": account.bank,
            "last4": account.account_last4,
            "period": f"{account.period.start} -> {account.period.end}",
        })

        tx_result = await self._transactions(
            ExtractTransactionsCommand(
                segment_text=seg.text,
                period_start=account.period.start,
                period_end=account.period.end,
            )
        )
        await self._event_bus.emit("transactions_done", {
            "label": label,
            "count": len(tx_result.transactions),
            "skipped": len(tx_result.skipped_rows),
        })

        initial_recon = await self._reconciler.reconcile(summary_vo, tx_result.transactions)

        final_txns = list(tx_result.transactions)
        final_recon = initial_recon
        history = [initial_recon]

        if not initial_recon.ok:
            fixed_txns, history = await self._repair(
                RepairStatementCommand(
                    segment_text=seg.text,
                    summary=summary_vo,
                    transactions=tx_result.transactions,
                    reconciliation=initial_recon,
                    period_start=account.period.start,
                    period_end=account.period.end,
                )
            )
            final_txns = fixed_txns
            final_recon = history[-1] if history else initial_recon

        if final_recon.ok and history and not history[0].ok:
            try:
                lessons = self._lessons_helper.diagnose_repair(
                    history[0], final_recon, tx_result.transactions, final_txns
                )
                for pattern_hash, hint in lessons:
                    await self._lessons.record(pattern_hash, hint, source=label)
                if lessons:
                    await self._event_bus.emit("lessons_recorded", {
                        "label": label, "count": len(lessons)
                    })
            except Exception:
                pass

        await self._event_bus.emit("segment_done", {
            "label": label,
            "reconciled": final_recon.ok,
            "issues": list(final_recon.issues),
        })

        if command.enrich and final_txns:
            try:
                final_txns = await self._enrich_cmd(
                    EnrichTransactionsCommand(transactions=final_txns)
                )
            except Exception:
                pass

        anomalies = await self._anomaly_detector.detect(
            final_txns, account.period.start, account.period.end
        )
        forensic = await self._forensic_detector.detect(final_txns)
        anomalies = list(anomalies) + list(forensic)

        if anomalies:
            await self._event_bus.emit("anomalies_found", {
                "label": label,
                "count": len(anomalies),
            })

        try:
            recurring = await self._recurring_detector.detect(final_txns)
        except Exception:
            recurring = []

        statement = Statement(
            oid=uuid4(),
            account=account,
            summary=summary_vo,
            transactions=final_txns,
            skipped_rows=tx_result.skipped_rows,
            reconciliation=final_recon,
            anomalies=anomalies,
            recurring=list(recurring),
        )

        if final_recon.ok:
            await self._cache.put(cache_key, statement)
            await self._event_bus.emit("cache_write", {
                "label": label, "key": cache_key
            })

        return statement

    async def __call__(self, command: ExtractStatementCommand) -> list[Statement]:
        import time
        started_at = time.time()

        await self._event_bus.emit("ingest_start", {
            "pdf": command.pdf_path,
            "txt": command.txt_path,
            "ocr_mode": command.ocr_mode,
        })

        if command.txt_path:
            text = await asyncio.to_thread(
                Path(command.txt_path).read_text, encoding="utf-8", errors="ignore"
            )
            await self._event_bus.emit("ocr_cache_hit", {
                "method": "txt-passthrough", "chars": len(text),
            })
        elif command.pdf_path:
            text = await self._ocr.extract_text(
                command.pdf_path,
                log_event=lambda name, data: asyncio.ensure_future(
                    self._event_bus.emit(name, data)
                ),
            )
        else:
            raise ValueError("ExtractStatementCommand requires pdf_path or txt_path")

        await self._event_bus.emit("ingest_done", {"chars": len(text)})

        segments = await self._segmenter.split(text)
        if not segments:
            await self._event_bus.emit("segment_fallback", {
                "reason": "regex found no boundaries, asking LLM"
            })
            segments = await self._segmenter.split_with_llm(text, self._llm)

        await self._event_bus.emit("segment_done_all", {
            "statement_count": len(segments),
            "periods": [s.period_start_raw for s in segments],
        })

        if not segments:
            return []

        sem = asyncio.Semaphore(command.parallel)
        results_maybe = await asyncio.gather(
            *(self._process_segment(seg, command, sem) for seg in segments),
            return_exceptions=False,
        )

        statements: list[Statement] = [s for s in results_maybe if s is not None]

        if len(statements) >= 2:
            continuity_issues = await self._continuity_auditor.audit(statements)
            if continuity_issues:
                await self._event_bus.emit("continuity_issues", {
                    "count": len(continuity_issues)
                })
                from dobs.domain.value_objects.anomaly import Anomaly
                issue_by_account: dict[str | None, list] = {}
                for iss in continuity_issues:
                    issue_by_account.setdefault(iss.account_last4, []).append(iss)
                for stmt in statements:
                    for iss in issue_by_account.get(stmt.account.account_last4, []):
                        stmt.anomalies.append(Anomaly(
                            kind="running_balance_drift",
                            severity="error",
                            transaction_index=None,
                            related_index=None,
                            message=(
                                f"[continuity] balance gap: expected "
                                f"{iss.expected_beginning:.2f} got "
                                f"{iss.actual_beginning:.2f}"
                            ),
                        ))

        try:
            await self._vendor.enrich_in_place([
                {"description": t.description, "vendor": t.vendor}
                for stmt in statements
                for t in stmt.transactions
            ])
        except Exception:
            pass

        try:
            tel = self._telemetry.summary()
            audit_rec = AuditRecord(
                oid=uuid4(),
                tier=command.tier,
                backend=getattr(self._llm, "name", None),
                source_filename=(
                    Path(command.pdf_path).name if command.pdf_path
                    else Path(command.txt_path).name if command.txt_path
                    else None
                ),
                statement_count=len(statements),
                reconciled_count=sum(
                    1 for s in statements if s.reconciliation and s.reconciliation.ok
                ),
                transactions_count=sum(len(s.transactions) for s in statements),
                total_cost_usd=float(tel.get("total_cost_usd", 0.0)),
                elapsed_s=round(time.time() - started_at, 2),
                metadata={
                    "ocr_mode": command.ocr_mode,
                    "enrich": command.enrich,
                    "parallel": command.parallel,
                    "telemetry": tel,
                },
            )
            audit_id = await self._audit.record(started_at, audit_rec)
            await self._event_bus.emit("audit_recorded", {
                "audit_id": audit_id,
                "total_cost_usd": round(audit_rec.total_cost_usd, 4),
                "elapsed_s": audit_rec.elapsed_s,
            })
        except Exception:
            pass

        return statements
