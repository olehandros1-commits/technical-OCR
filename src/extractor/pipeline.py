"""End-to-end orchestrator wiring all six stages together.

Public API:
    extract(pdf_path, txt_path=None) -> dict      # the exact spec contract
    extract_all(pdf_path, txt_path=None) -> list[dict]  # multi-statement

The pipeline is backend-agnostic. Pick a backend via:
  - the `backend` kwarg
  - the EXTRACTOR_BACKEND env var (anthropic / ollama)
  - default: anthropic
"""
from __future__ import annotations
import concurrent.futures as cf
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from extractor.backends import LLMBackend, get_backend
from extractor.ingest import ingest
from extractor.segment import split_statements, split_statements_llm, StatementSegment
from extractor.extract_summary import extract_summary
from extractor.extract_transactions import extract_transactions
from extractor.repair import repair_loop
from extractor.reconcile import reconcile
from extractor.enrich import enrich_transactions
from extractor.anomaly import detect_anomalies
from extractor.forensic import forensic_anomalies
from extractor.continuity import audit_continuity
from extractor.recurring import detect_recurring
from extractor.cache import StatementCache
from extractor.cache_redis import open_cache
from extractor.tracing import span
from extractor.prompt_lessons import LessonsStore, diagnose_repair, lessons_block
from extractor.tiers import get_tier, apply_tier_env
from extractor.audit import AuditLog, AuditRecord
from extractor.telemetry import get_collector
from extractor.schemas import Statement


# Process-wide audit log -- one file, append-only.
_AUDIT_LOG: AuditLog | None = None


def _audit_log() -> AuditLog:
    global _AUDIT_LOG
    if _AUDIT_LOG is None:
        import os
        _AUDIT_LOG = AuditLog(Path(os.getenv("AUDIT_LOG_DB", "out/audit.db")))
    return _AUDIT_LOG


# Module-level lessons store -- the prompt's self-improvement scratchpad.
_LESSONS_STORE: LessonsStore | None = None


def _lessons_store() -> LessonsStore:
    global _LESSONS_STORE
    if _LESSONS_STORE is None:
        import os
        path = Path(os.getenv("LESSONS_DB", "out/lessons.db"))
        _LESSONS_STORE = LessonsStore(path)
    return _LESSONS_STORE

log = logging.getLogger(__name__)


EventLogger = Callable[[str, dict], None]


def _segment_cache_key(seg: StatementSegment, backend_name: str) -> str:
    """Hash of (tenant, segment text, backend name).

    Tenant prefix keeps multi-tenant caches isolated; the absence of a
    tenant binds to a `_default` namespace so single-tenant deploys are
    unaffected.
    """
    from extractor.tenant import current_tenant
    h = hashlib.sha256(
        f"{backend_name}|{seg.text}".encode("utf-8")
    ).hexdigest()[:16]
    return (
        f"{current_tenant()}::"
        f"{seg.period_start_raw.replace('/', '-')}_"
        f"{seg.account_hint or 'none'}_{backend_name}_{h}"
    )


def _process_segment(
    seg: StatementSegment,
    backend: LLMBackend,
    *,
    log_event: Optional[EventLogger] = None,
    cache: Optional[StatementCache] = None,
    enrich: bool = False,
) -> Statement:
    label = f"{seg.period_start_raw} acct {seg.account_hint or '?'}"

    cache_key = _segment_cache_key(seg, backend.name)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            if log_event:
                log_event("cache_hit", {"label": label, "backend": backend.name, "key": cache_key})
            return cached

    if log_event:
        log_event("segment_start", {"label": label, "chars": len(seg.text), "backend": backend.name})

    t0 = time.time()
    with span("extract.summary", {"label": label, "backend": backend.name}):
        summary_resp = extract_summary(seg.text, backend)
    if log_event:
        log_event(
            "summary_done",
            {
                "label": label,
                "bank": summary_resp.account.bank,
                "last4": summary_resp.account.account_last4,
                "period": f"{summary_resp.account.period.start} -> "
                          f"{summary_resp.account.period.end}",
                "elapsed_s": round(time.time() - t0, 2),
            },
        )

    t1 = time.time()
    with span("extract.transactions", {"label": label}):
        tx_resp = extract_transactions(
            seg.text,
            summary_resp.account.period.start,
            summary_resp.account.period.end,
            backend,
        )
    if log_event:
        log_event(
            "transactions_done",
            {
                "label": label,
                "count": len(tx_resp.transactions),
                "skipped": len(tx_resp.skipped_rows),
                "elapsed_s": round(time.time() - t1, 2),
            },
        )

    with span("extract.repair", {"label": label}):
        final_txns, final_recon, history = repair_loop(
            seg.text,
            summary_resp.account.period.start,
            summary_resp.account.period.end,
            summary_resp.summary,
            tx_resp.transactions,
            backend,
            log_event=log_event,
        )

    # RLAIF-lite: persist what we learned from the repair so subsequent
    # extractions get few-shot hints based on past mistakes.
    if final_recon.ok and history and not history[0].ok:
        try:
            lessons = diagnose_repair(
                history[0], final_recon, tx_resp.transactions, final_txns,
            )
            store = _lessons_store()
            for pattern_hash, hint in lessons:
                store.record(pattern_hash, hint, source=label)
            if lessons and log_event:
                log_event("lessons_recorded", {
                    "label": label, "count": len(lessons),
                    "patterns": [p for p, _ in lessons],
                })
        except Exception as e:
            log.warning("lessons store failed: %s", e)

    if log_event:
        log_event(
            "segment_done",
            {
                "label": label,
                "reconciled": final_recon.ok,
                "issues": final_recon.issues,
            },
        )

    # Optional Stage 4.5: enrichment (category + vendor + confidence).
    if enrich and final_txns:
        if log_event:
            log_event("enrich_start", {"label": label, "count": len(final_txns)})
        t_enr = time.time()
        try:
            final_txns = enrich_transactions(final_txns, backend)
            if log_event:
                log_event("enrich_done", {
                    "label": label,
                    "elapsed_s": round(time.time() - t_enr, 2),
                    "with_category": sum(1 for t in final_txns if t.category),
                })
        except Exception as e:
            if log_event:
                log_event("enrich_error", {"label": label, "error": str(e)})

    # Stage 8: anomaly detection (deterministic, no LLM, fast).
    anomalies = detect_anomalies(
        final_txns,
        summary_resp.account.period.start,
        summary_resp.account.period.end,
    )
    # Stage 9: forensic / anti-fraud rules (Benford, vendor concentration,
    # velocity, weekend, round numbers). Same Anomaly schema, prefixed
    # messages so the UI can group by source.
    anomalies.extend(forensic_anomalies(final_txns))
    if log_event and anomalies:
        log_event("anomalies_found", {
            "label": label,
            "count": len(anomalies),
            "by_kind": {
                k: sum(1 for a in anomalies if a.kind == k)
                for k in {a.kind for a in anomalies}
            },
        })

    # Stage 10: recurring-transaction detection (deterministic).
    # Subscription / payroll / rent clustering. Empty when nothing
    # recurring is found; never raises.
    try:
        recurring = [g.to_dict() for g in detect_recurring(final_txns)]
    except Exception as e:
        log.warning("recurring detection failed: %s", e)
        recurring = []

    statement = Statement(
        account=summary_resp.account,
        summary=summary_resp.summary,
        transactions=final_txns,
        skipped_rows=tx_resp.skipped_rows,
        reconciliation=final_recon,
        anomalies=anomalies,
        recurring=recurring,
    )

    if cache is not None and final_recon.ok:
        cache.put(cache_key, statement)
        if log_event:
            log_event("cache_write", {"label": label, "key": cache_key})

    return statement


def extract_all(
    pdf_path: str,
    txt_path: str | None = None,
    *,
    backend: LLMBackend | str | None = None,
    tier: str | None = None,
    parallel: int = 2,
    ocr_mode: str = "auto",
    enrich: bool = False,
    log_event: Optional[EventLogger] = None,
    cache_path: str | Path | None = "out/cache.db",
    operator: str | None = None,
    client_ip: str | None = None,
) -> list[dict]:
    """Run the full pipeline. Returns one grading-shaped dict per statement.

    backend may be: an LLMBackend instance, a string name ('anthropic'/'ollama'),
    or None (uses EXTRACTOR_BACKEND env or 'anthropic' default).

    ocr_mode controls how scanned PDFs are turned into text:
      'auto'      - text-extract then Tesseract fallback (default)
      'tesseract' - force Tesseract
      'vision'    - render pages as images, OCR via vision LLM (uses backend)
      'skip'      - never OCR; useful when txt_path is provided
    """
    # Apply tier-named defaults (model mapping + ocr mode + enrich).
    # When a tier is set, it WINS over default-valued `backend` / `ocr_mode`
    # hints from the caller. UI disables the backend dropdown when a tier
    # is selected for exactly this reason; a stale form default like
    # "anthropic" must not silently route a tier=local request to cloud.
    if tier is not None or os.getenv("EXTRACTOR_TIER"):
        try:
            tier_obj = get_tier(tier)
            apply_tier_env(tier_obj)
            # Tier always selects its backend. Caller can still pass a
            # custom LLMBackend instance to override; only string hints
            # are superseded by the tier.
            if backend is None or isinstance(backend, str):
                backend = tier_obj.backend
            # 'auto' is the form default, treat it as "no opinion" and
            # let the tier pick.
            if ocr_mode == "auto":
                ocr_mode = tier_obj.ocr_mode
            if log_event:
                log_event("tier_active", {
                    "tier": tier_obj.name,
                    "display": tier_obj.display,
                    "backend": tier_obj.backend,
                    "ocr_mode": tier_obj.ocr_mode,
                    "cost_low_usd": tier_obj.expected_cost_usd[0],
                    "cost_high_usd": tier_obj.expected_cost_usd[1],
                })
        except ValueError as e:
            if log_event:
                log_event("tier_error", {"error": str(e)})

    started_at = time.time()
    audit = AuditRecord(
        tier=tier,
        operator=operator,
        client_ip=client_ip,
        source_filename=Path(pdf_path).name if pdf_path else None,
    )

    # Demo replay: zero-cost UX-identical playback of a saved snapshot.
    from extractor.demo_replay import is_replay_enabled, replay
    if is_replay_enabled():
        if log_event:
            log_event("demo_replay_active", {
                "reason": "EXTRACTOR_DEMO_REPLAY=1",
                "tier": tier or "balanced",
            })
        results = replay(log_event=log_event, tier=tier)
        for r in results:
            r.setdefault("_anomalies", r.get("_anomalies", []))
        # Replay runs still produce an audit row -- otherwise the audit
        # log is unaware of demo activity and tests assert a tail entry
        # against a pre-existing row from a prior session.
        try:
            audit.backend = "demo-replay"
            audit.statement_count = len(results)
            audit.reconciled_count = sum(
                1 for o in results
                if (o.get("_reconciliation") or {}).get("ok")
            )
            audit.transactions_count = sum(len(o["transactions"]) for o in results)
            audit.total_cost_usd = 0.0
            audit.elapsed_s = round(time.time() - started_at, 2)
            audit.metadata = {"mode": "demo_replay", "tier": tier or "balanced"}
            audit_id = _audit_log().record(started_at, audit)
            if log_event:
                log_event("audit_recorded", {
                    "audit_id": audit_id,
                    "total_cost_usd": 0.0,
                    "elapsed_s": audit.elapsed_s,
                })
        except Exception as e:
            log.warning("audit log write failed (replay path): %s", e)
        return results

    if backend is None or isinstance(backend, str):
        backend_obj = get_backend(backend)
    else:
        backend_obj = backend

    if log_event:
        log_event("ingest_start", {
            "pdf": pdf_path, "txt": txt_path,
            "backend": backend_obj.name, "ocr_mode": ocr_mode,
        })
    text = ingest(
        pdf_path, txt_path,
        ocr_mode=ocr_mode, backend=backend_obj,
        log_event=log_event,
    )
    if log_event:
        log_event("ingest_done", {"chars": len(text)})

    segments = split_statements(text)
    if not segments:
        if log_event:
            log_event("segment_fallback", {"reason": "regex found no boundaries, asking LLM"})
        segments = split_statements_llm(text, backend_obj)

    if log_event:
        log_event(
            "segment_done_all",
            {"statement_count": len(segments),
             "periods": [s.period_start_raw for s in segments]},
        )

    if not segments:
        return []

    # cache_path can be a Redis URL, "memory", or a filesystem path.
    if cache_path is None:
        cache = None
    else:
        cache_str = str(cache_path)
        # Prefer the unified resolver; falls back gracefully when Redis is unreachable.
        if (cache_str.startswith("redis://")
                or cache_str.startswith("rediss://")
                or cache_str == "memory"
                or cache_str.startswith("sqlite:")):
            cache = open_cache(cache_str)
        else:
            cache = StatementCache(Path(cache_str))

    statements: list[Statement | None] = [None] * len(segments)
    with cf.ThreadPoolExecutor(max_workers=parallel) as pool:
        future_to_idx = {
            pool.submit(
                _process_segment,
                seg,
                backend_obj,
                log_event=log_event,
                cache=cache,
                enrich=enrich,
            ): i
            for i, seg in enumerate(segments)
        }
        for fut in cf.as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                statements[i] = fut.result()
            except Exception as e:
                log.exception("Segment %d failed", i)
                if log_event:
                    log_event("segment_error", {"index": i, "error": str(e)})

    out: list[dict] = []
    for s in statements:
        if s is None:
            continue
        d = s.to_grading_dict()
        d["_reconciliation"] = s.reconciliation.model_dump() if s.reconciliation else None
        d["_skipped_rows"] = [r.model_dump() for r in s.skipped_rows]
        d["_anomalies"] = [a.model_dump() for a in s.anomalies]
        d["_recurring"] = list(s.recurring)
        # Post-process: attach polished vendor metadata (logo, domain,
        # canonical name) where the enrich stage gave us a vendor field.
        # Skipped silently when there's no vendor or the lookup chain
        # has no hit (deterministic-only seed file empty + Clearbit
        # unreachable). Never raises.
        try:
            from extractor.vendor_lookup import enrich_vendors_in_place
            enrich_vendors_in_place(d["transactions"])
        except Exception as e:
            log.debug("vendor enrichment skipped: %s", e)
        out.append(d)

    # Cross-statement continuity audit (deterministic, fast). Each issue
    # is appended to every involved statement's _anomalies, so single-
    # statement consumers still see the problem.
    if len(out) >= 2:
        issues = audit_continuity(out)
        if issues and log_event:
            log_event("continuity_issues", {"count": len(issues)})
        per_period = {(o["account"]["period"]["start"], o["account"]["account_last4"]): o
                      for o in out}
        for iss in issues:
            msg = iss.to_dict()["message"]
            for period in (iss.prev_period, iss.next_period):
                target = per_period.get((period, iss.account_last4))
                if target is None:
                    continue
                target.setdefault("_anomalies", []).append({
                    "kind": "running_balance_drift",
                    "severity": "error",
                    "transaction_index": None,
                    "related_index": None,
                    "message": "[continuity] " + msg,
                })

    # Audit log -- one row per extraction call, never silently dropped.
    try:
        tel = get_collector().summary()
        audit.backend = (backend if isinstance(backend, str)
                         else getattr(backend_obj, "name", None))
        audit.statement_count = len(out)
        audit.reconciled_count = sum(
            1 for o in out if (o.get("_reconciliation") or {}).get("ok")
        )
        audit.transactions_count = sum(len(o["transactions"]) for o in out)
        audit.total_cost_usd = float(tel.get("total_cost_usd", 0.0))
        audit.elapsed_s = round(time.time() - started_at, 2)
        if pdf_path and Path(pdf_path).exists():
            from extractor.ingest import _file_hash as _hash
            audit.source_sha256 = _hash(Path(pdf_path))
        audit.metadata = {
            "ocr_mode": ocr_mode,
            "enrich": enrich,
            "parallel": parallel,
            "telemetry": tel,
        }
        audit_id = _audit_log().record(started_at, audit)
        if log_event:
            log_event("audit_recorded", {
                "audit_id": audit_id,
                "total_cost_usd": round(audit.total_cost_usd, 4),
                "elapsed_s": audit.elapsed_s,
            })
    except Exception as e:
        log.warning("audit log write failed: %s", e)

    return out


def extract(
    pdf_path: str,
    txt_path: str | None = None,
    *,
    backend: LLMBackend | str | None = None,
) -> dict:
    """Spec-conforming entry point: returns ONE statement (the first one)."""
    results = extract_all(pdf_path, txt_path, backend=backend, parallel=1)
    if not results:
        return {}
    first = results[0]
    return {k: v for k, v in first.items() if not k.startswith("_")}
