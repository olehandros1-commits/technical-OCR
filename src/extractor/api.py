"""HTTP API for the bank-statement extractor.

Endpoints:
  GET  /health                       -> service liveness
  POST /extract                      -> blocking extract, returns final JSON
  POST /jobs                         -> async job, returns job_id
  GET  /jobs/{job_id}/events         -> Server-Sent Events stream of progress
  GET  /jobs/{job_id}                -> final result of an async job
  GET  /telemetry                    -> aggregate token / cost stats
  POST /reviews                      -> persist a HITL approve/reject decision
  GET  /reviews/{statement_key}      -> decisions on one statement

OpenAPI docs at /docs (Swagger UI) and /redoc.

Run with:
    uvicorn extractor.api:app --reload --port 8000
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from extractor.security_api import api_key_dependency, configured_cors
from extractor.tenant import tenant_scope

from extractor.pipeline import extract_all
from extractor.telemetry import TelemetryCollector, set_collector, get_collector
from extractor.reviews import Review, ReviewStore, Decision
from extractor.ingest import (
    EncryptedDocumentError,
    EmptyDocumentError,
    CorruptDocumentError,
    UnsupportedFormatError,
    IngestError,
)
from extractor.export_excel import export_workbook
from fastapi.responses import FileResponse

load_dotenv()
log = logging.getLogger(__name__)

REVIEW_STORE = ReviewStore(Path(os.getenv("REVIEW_DB", "out/reviews.db")))


def _maybe_warm_up() -> None:
    """Fire-and-forget prompt-cache warm-up on first health check / first hit."""
    if os.getenv("EXTRACTOR_WARMUP", "1") not in {"1", "true", "yes"}:
        return
    from extractor.backends import get_backend
    from extractor.warmup import warm_up_backend
    try:
        backend = get_backend()
        # Run in background so the API listener is not blocked.
        threading.Thread(
            target=lambda: warm_up_backend(backend), daemon=True,
        ).start()
    except Exception as e:
        log.warning("warm-up skipped: %s", e)

app = FastAPI(
    title="Bank Statement Extractor",
    version="0.3.0",
    description=(
        "Extract reconciled, structured JSON / Excel workbooks from bank "
        "statement PDFs (and images, xlsx, html). Hybrid deterministic + "
        "LLM pipeline with adaptive repair, categorisation, anomaly + "
        "forensic detection, cross-statement continuity, and HITL review."
    ),
)

_cors = configured_cors()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False if _cors == ["*"] else True,
)


# ---------- Job registry (in-process) ------------------------------------
# For a production deploy this would be Redis / a queue, but for a single
# demo box an in-process dict is sufficient and dependency-free.

class _Job:
    __slots__ = ("id", "queue", "result", "error", "done", "started_at")

    def __init__(self, job_id: str):
        self.id = job_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.result: list | None = None
        self.error: str | None = None
        self.done: bool = False
        self.started_at: float = time.time()


_JOBS: dict[str, _Job] = {}
_JOBS_LOCK = threading.Lock()


def _new_job() -> _Job:
    job = _Job(str(uuid.uuid4()))
    with _JOBS_LOCK:
        _JOBS[job.id] = job
    return job


def _get_job(job_id: str) -> _Job:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------- Schemas ------------------------------------------------------

class ExtractRequest(BaseModel):
    """Sent as multipart/form-data parts -- this is documentation only."""
    pdf: bytes
    txt: Optional[bytes] = None
    backend: str = "anthropic"
    ocr_mode: str = "auto"
    enrich: bool = True
    parallel: int = 2


class ReviewIn(BaseModel):
    statement_key: str
    tx_index: int
    decision: Decision
    reviewer: Optional[str] = None
    note: Optional[str] = None


# ---------- Helpers ------------------------------------------------------

def _persist_uploads(pdf: UploadFile, txt: UploadFile | None) -> tuple[Path, Path | None]:
    tmp = Path(tempfile.mkdtemp(prefix="bse_"))
    pdf_path = tmp / (pdf.filename or "upload.pdf")
    pdf_path.write_bytes(pdf.file.read())
    txt_path: Path | None = None
    if txt is not None:
        txt_path = tmp / (txt.filename or "upload.txt")
        txt_path.write_bytes(txt.file.read())
    return pdf_path, txt_path


def _run_extract_with_events(
    pdf_path: Path,
    txt_path: Path | None,
    backend: str,
    ocr_mode: str,
    enrich: bool,
    parallel: int,
    queue: asyncio.Queue | None,
    loop: asyncio.AbstractEventLoop | None,
    tier: str | None = None,
    operator: str | None = None,
    client_ip: str | None = None,
) -> list[dict]:
    """Run the pipeline; if a queue is supplied, stream events to it."""
    set_collector(TelemetryCollector())

    def log_event(name: str, data: dict) -> None:
        if queue is None or loop is None:
            return
        payload = {"event": name, "data": data, "ts": time.time()}
        # asyncio.Queue is loop-affined; schedule from the worker thread.
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    # tenant comes via X-Tenant-ID header in the request handlers below;
    # caller propagates it as `operator` until we wire a dedicated arg.
    return extract_all(
        str(pdf_path),
        str(txt_path) if txt_path else None,
        backend=backend if backend else None,
        tier=tier,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        operator=operator,
        client_ip=client_ip,
        log_event=log_event,
    )


# ---------- Endpoints ----------------------------------------------------

_WARMED = {"done": False}


@app.get("/health", tags=["meta"])
def health() -> dict:
    # Trigger warm-up on first hit (so we don't slow down startup itself).
    if not _WARMED["done"]:
        _WARMED["done"] = True
        _maybe_warm_up()
    return {"ok": True, "service": "bank-statement-extractor"}


@app.post("/extract", tags=["extract"])
def extract_blocking(
    pdf: UploadFile = File(..., description="Bank statement PDF"),
    txt: UploadFile | None = File(None, description="Pre-OCR'd text (optional)"),
    backend: str = Form("", description="anthropic or ollama (empty = pick from tier)"),
    tier: str = Form("", description="premium / balanced / cheap / local"),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
    x_tenant_id: str = Header(default="", convert_underscores=False),
) -> dict:
    """Synchronous extraction. Returns the result inline.

    Use this for small statements where streaming progress is unnecessary.
    For long-running extractions prefer POST /jobs + GET /jobs/{id}/events.
    """
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    try:
        with tenant_scope(x_tenant_id):
            results = _run_extract_with_events(
                pdf_path, txt_path, backend, ocr_mode, enrich, parallel,
                queue=None, loop=None, tier=tier or None,
            )
    except EncryptedDocumentError as e:
        raise HTTPException(status_code=422, detail={"kind": "encrypted", "message": str(e)})
    except EmptyDocumentError as e:
        raise HTTPException(status_code=422, detail={"kind": "empty", "message": str(e)})
    except CorruptDocumentError as e:
        raise HTTPException(status_code=422, detail={"kind": "corrupt", "message": str(e)})
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=415, detail={"kind": "unsupported", "message": str(e)})
    except IngestError as e:
        raise HTTPException(status_code=422, detail={"kind": "ingest", "message": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "results": results,
        "telemetry": get_collector().summary(),
    }


@app.post("/export/xlsx", tags=["export"])
def export_xlsx_blocking(
    pdf: UploadFile = File(...),
    txt: UploadFile | None = File(None),
    backend: str = Form("anthropic"),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(True),
    parallel: int = Form(2),
) -> FileResponse:
    """One-shot: extract + write a multi-sheet Excel workbook with live
    SUMIF formulas, conditional formatting, and a continuity audit. The
    workbook is returned as a download."""
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    try:
        results = _run_extract_with_events(
            pdf_path, txt_path, backend, ocr_mode, enrich, parallel,
            queue=None, loop=None,
        )
    except IngestError as e:
        raise HTTPException(status_code=422, detail=str(e))
    out_dir = Path(tempfile.mkdtemp(prefix="bse_xlsx_"))
    out_file = out_dir / f"{pdf.filename or 'statement'}.xlsx"
    export_workbook(results, out_file)
    return FileResponse(
        str(out_file),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out_file.name,
    )


@app.post("/jobs", tags=["jobs"])
async def create_job(
    pdf: UploadFile = File(...),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
    callback_url: str = Form("", description="If set, POST results here when done."),
    x_tenant_id: str = Header(default="", convert_underscores=False),
) -> dict:
    """Start an async extraction job. Returns a job_id you stream via SSE.

    When `callback_url` is provided, the server POSTs the final results
    JSON to that URL when the job completes -- handy for Slack /
    Zapier / n8n / ERP integrations.
    """
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    job = _new_job()
    loop = asyncio.get_running_loop()

    tenant_for_job = x_tenant_id

    def worker():
        try:
            with tenant_scope(tenant_for_job):
                results = _run_extract_with_events(
                    pdf_path, txt_path, backend, ocr_mode, enrich, parallel,
                    queue=job.queue, loop=loop, tier=tier or None,
                )
            job.result = results
        except Exception as e:
            job.error = str(e)
            loop.call_soon_threadsafe(
                job.queue.put_nowait,
                {"event": "error", "data": {"error": str(e)}, "ts": time.time()},
            )
        finally:
            job.done = True
            loop.call_soon_threadsafe(
                job.queue.put_nowait,
                {"event": "done", "data": {"elapsed_s": time.time() - job.started_at}, "ts": time.time()},
            )
            # Fire webhook last, after the SSE stream has had a chance to
            # forward the final 'done' event.
            if callback_url:
                _fire_webhook(callback_url, job)

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job.id}


def _fire_webhook(url: str, job: "_Job") -> None:
    """Best-effort POST of job results to a third-party endpoint."""
    try:
        import urllib.request
        import urllib.error
        payload = json.dumps({
            "job_id": job.id,
            "status": "failed" if job.error else "done",
            "elapsed_s": time.time() - job.started_at,
            "error": job.error,
            "results": job.result or [],
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).read()
        log.info("webhook delivered: %s", url)
    except Exception as e:
        log.warning("webhook delivery failed (%s): %s", url, e)


@app.get("/jobs/{job_id}/events", tags=["jobs"])
async def stream_job(job_id: str) -> StreamingResponse:
    """Server-Sent Events stream of pipeline events for a job."""
    job = _get_job(job_id)

    async def event_source():
        # Replay nothing -- jobs are short-lived; clients connect immediately.
        # We emit each event THREE ways for max client compatibility:
        #   1. `event: <name>` directive (clients with addEventListener(name, ...))
        #   2. as a default 'message' event so clients with `onmessage` catch it
        #   3. SSE comment heartbeat every 3 s so proxies / browsers never
        #      see a silent connection and time out.
        async def heartbeat_loop():
            while not job.done:
                await asyncio.sleep(3)
                # Re-fire a synthetic heartbeat into the queue so the main
                # loop wakes up and forwards it.
                if not job.done:
                    job.queue.put_nowait({
                        "event": "heartbeat",
                        "data": {"elapsed_s": round(time.time() - job.started_at, 1)},
                        "ts": time.time(),
                    })

        asyncio.create_task(heartbeat_loop())

        while True:
            payload = await job.queue.get()
            # We intentionally emit WITHOUT a `event:` directive so every
            # message routes to EventSource.onmessage on the client. SSE
            # named events would otherwise force callers to register one
            # addEventListener per event-name, which is fragile when the
            # backend evolves.
            wire = {
                "event": payload["event"],
                "data": payload["data"],
                "ts": payload["ts"],
            }
            yield f"data: {json.dumps(wire)}\n\n"
            if payload["event"] == "done":
                return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable buffering in nginx
        },
    )


@app.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str) -> dict:
    """Get the final result of an async job. Returns 202 if still running."""
    job = _get_job(job_id)
    if not job.done:
        return JSONResponse(
            status_code=202,
            content={"status": "running", "elapsed_s": time.time() - job.started_at},
        )
    if job.error:
        raise HTTPException(status_code=500, detail=job.error)
    return {
        "status": "done",
        "elapsed_s": time.time() - job.started_at,
        "results": job.result,
        "telemetry": get_collector().summary(),
    }


@app.get("/telemetry", tags=["meta"])
def telemetry() -> dict:
    """Last run's telemetry (tokens, cost, latency)."""
    return get_collector().summary()


@app.get("/tiers", tags=["meta"])
def tiers() -> dict:
    """Catalog of named tiers (premium / balanced / cheap / local) with
    expected cost + latency + model mix, for the UI tier selector."""
    from extractor.tiers import all_tiers
    return {
        "tiers": [
            {
                "name": t.name,
                "display": t.display,
                "description": t.description,
                "backend": t.backend,
                "model_cheap":   t.model_cheap,
                "model_extract": t.model_extract,
                "model_repair":  t.model_repair,
                "expected_latency_s": list(t.expected_latency_s),
                "expected_cost_usd":  list(t.expected_cost_usd),
                "enrich_default": t.enrich_default,
                "ocr_mode": t.ocr_mode,
            }
            for t in all_tiers()
        ],
    }


@app.get("/audit", tags=["meta"])
def audit(limit: int = 50) -> dict:
    """Recent audit log entries (every extraction is recorded)."""
    from extractor.pipeline import _audit_log
    return {"records": _audit_log().recent(limit=limit)}


def _open_default_cache():
    """Resolve the statement cache the pipeline is using right now."""
    from extractor.cache_redis import open_cache
    path = os.getenv("EXTRACTOR_CACHE_URL") or "out/cache.db"
    return open_cache(path)


@app.get("/cache/keys", tags=["cache"])
def cache_keys(limit: int = 200) -> dict:
    """List cached statement keys. Useful for tooling / debug."""
    cache = _open_default_cache()
    if cache is None or not hasattr(cache, "keys"):
        return {"keys": [], "note": "cache backend does not support listing"}
    return {"keys": cache.keys(limit=limit)}


@app.delete("/cache/{key}", tags=["cache"])
def cache_delete(key: str) -> dict:
    """Bust one statement so the next extract recomputes it.

    Use after a prompt change / model swap when you want to force a
    fresh extraction on a specific statement instead of every cached
    one.
    """
    cache = _open_default_cache()
    if cache is None or not hasattr(cache, "delete"):
        raise HTTPException(status_code=500, detail="cache backend does not support delete")
    removed = cache.delete(key)
    return {"key": key, "removed": removed}


@app.post("/cache/clear", tags=["cache"])
def cache_clear() -> dict:
    """Wipe the entire statement cache. Audit log is preserved."""
    cache = _open_default_cache()
    if cache is None or not hasattr(cache, "clear"):
        raise HTTPException(status_code=500, detail="cache backend does not support clear")
    n = cache.clear()
    return {"removed": n}


class DiffIn(BaseModel):
    a: dict     # earlier extraction result
    b: dict     # later extraction result


@app.post("/diff", tags=["tooling"])
def post_diff(req: DiffIn) -> dict:
    """Structured diff between two extractions of the same statement.

    Used to QA prompt / model changes: 'I tuned X; show me what
    actually changed in the output for this statement.'
    """
    from extractor.diff_extractions import diff_extractions
    return diff_extractions(req.a, req.b).to_dict()


@app.post("/extract/bulk", tags=["extract"])
async def extract_bulk(
    files: list[UploadFile] = File(..., description="Multiple PDFs (or one ZIP)."),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> dict:
    """Bulk extract: drop a folder's worth of PDFs (or a ZIP). Returns
    one results-per-file dict so the caller can render a combined report.

    Each file is processed independently; one failure does not abort the
    rest. ZIP archives are unpacked in-process to keep the API self-
    contained.
    """
    import zipfile
    tmp = Path(tempfile.mkdtemp(prefix="bse_bulk_"))
    pdfs: list[Path] = []
    for f in files:
        body = await f.read()
        name = f.filename or "upload.bin"
        path = tmp / name
        path.write_bytes(body)
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(tmp / Path(name).stem)
            except zipfile.BadZipFile:
                continue
            for p in (tmp / Path(name).stem).rglob("*.pdf"):
                pdfs.append(p)
        elif name.lower().endswith(".pdf"):
            pdfs.append(path)

    bundle: list[dict] = []
    for p in pdfs:
        try:
            results = extract_all(
                str(p),
                backend=backend or None, tier=tier or None,
                ocr_mode=ocr_mode, enrich=enrich, parallel=parallel,
            )
            bundle.append({"filename": p.name, "ok": True, "results": results})
        except Exception as e:
            bundle.append({"filename": p.name, "ok": False, "error": str(e)})

    return {
        "files_count": len(pdfs),
        "bundle": bundle,
        "telemetry": get_collector().summary(),
    }


class ExplainIn(BaseModel):
    anomaly: dict
    transaction: dict | None = None
    context_transactions: list[dict] | None = None


@app.post("/explain", tags=["hitl"])
def post_explain(req: ExplainIn) -> dict:
    """Cheap LLM explanation of one flagged anomaly. Returns a 1-3-sentence
    summary + suggested action so a reviewer can decide quickly."""
    from extractor.backends import get_backend
    from extractor.explain import explain_anomaly
    try:
        backend = get_backend()
        out = explain_anomaly(
            backend,
            anomaly=req.anomaly,
            transaction=req.transaction,
            context_transactions=req.context_transactions,
        )
        return out.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reviews", tags=["hitl"])
def post_review(r: ReviewIn) -> dict:
    """Record a human review decision on a specific transaction."""
    review_id = REVIEW_STORE.record(Review(
        statement_key=r.statement_key,
        tx_index=r.tx_index,
        decision=r.decision,
        reviewer=r.reviewer,
        note=r.note,
    ))
    return {"id": review_id, "status": "recorded"}


@app.get("/reviews/{statement_key}", tags=["hitl"])
def get_reviews(statement_key: str) -> dict:
    """All current review decisions for a statement, keyed by tx_index."""
    decisions = REVIEW_STORE.latest_for_statement(statement_key)
    return {
        "statement_key": statement_key,
        "decisions": {
            str(idx): {
                "decision": r.decision,
                "reviewer": r.reviewer,
                "note": r.note,
            }
            for idx, r in decisions.items()
        },
    }
