from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from dobs.presentation.api.http.middleware.api_key import api_key_dependency
from dobs.presentation.api.http.v1.extraction.job_registry import JobEntry, get_job_registry
from dobs.presentation.api.http.v1.extraction.schemas import (
    ExtractResponse,
    JobCreatedResponse,
    JobResultResponse,
)

router = APIRouter(
    prefix="/api/v1/extraction",
    tags=["extraction"],
    dependencies=[Depends(api_key_dependency)],
)


def get_extract_handler():
    raise NotImplementedError("Composition root must wire ExtractStatementHandler via dependency_overrides")


def _persist_uploads(pdf: UploadFile, txt: UploadFile | None) -> tuple[Path, Path | None]:
    tmp = Path(tempfile.mkdtemp(prefix="dobs_"))
    pdf_path = tmp / (pdf.filename or "upload.pdf")
    pdf_path.write_bytes(pdf.file.read())
    txt_path: Path | None = None
    if txt is not None:
        txt_path = tmp / (txt.filename or "upload.txt")
        txt_path.write_bytes(txt.file.read())
    return pdf_path, txt_path


@router.post("/extract", status_code=status.HTTP_200_OK, response_model=ExtractResponse)
async def extract(
    pdf: UploadFile = File(...),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
    handler=Depends(get_extract_handler),
) -> ExtractResponse:
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    results = await handler(
        pdf_path=pdf_path,
        txt_path=txt_path,
        backend=backend or None,
        tier=tier or None,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
    )
    return ExtractResponse(results=results, telemetry={})


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreatedResponse)
async def create_job(
    pdf: UploadFile = File(...),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
    handler=Depends(get_extract_handler),
) -> JobCreatedResponse:
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    job_id = str(uuid.uuid4())
    registry = get_job_registry()

    from dobs.presentation.api.http.v1.extraction.job_registry import JobEntry

    class _SimpleEventBus:
        def __init__(self) -> None:
            self._queue: asyncio.Queue = asyncio.Queue()

        async def publish(self, event_name: str, data: dict) -> None:
            await self._queue.put({"event": event_name, "data": data})

        async def get(self) -> dict:
            return await self._queue.get()

    event_bus = _SimpleEventBus()

    async def _run() -> None:
        try:
            results = await handler(
                pdf_path=pdf_path,
                txt_path=txt_path,
                backend=backend or None,
                tier=tier or None,
                ocr_mode=ocr_mode,
                enrich=enrich,
                parallel=parallel,
                event_bus=event_bus,
            )
            await registry.mark_done(job_id, result=results)
        except Exception as exc:
            await registry.mark_done(job_id, error=str(exc))
        finally:
            await event_bus.publish("done", {})

    task = asyncio.create_task(_run())
    await registry.register_job(job_id, event_bus, task)
    return JobCreatedResponse(job_id=job_id)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    registry = get_job_registry()
    entry: JobEntry | None = await registry.get_job(job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def _stream():
        while True:
            msg = await entry.event_bus.get()
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("event") == "done":
                break

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/jobs/{job_id}", response_model=JobResultResponse)
async def get_job(job_id: str) -> JobResultResponse:
    registry = get_job_registry()
    result, error, done = await registry.result_of(job_id)
    if result is None and error == "Job not found":
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResultResponse(job_id=job_id, done=done, results=result, error=error)


@router.post("/extract/bulk", status_code=status.HTTP_200_OK)
async def extract_bulk(
    files: list[UploadFile] = File(...),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
    handler=Depends(get_extract_handler),
) -> dict:
    all_results = []
    for upload in files:
        tmp = Path(tempfile.mkdtemp(prefix="dobs_bulk_"))
        pdf_path = tmp / (upload.filename or "upload.pdf")
        pdf_path.write_bytes(upload.file.read())
        results = await handler(
            pdf_path=pdf_path,
            txt_path=None,
            backend=backend or None,
            tier=tier or None,
            ocr_mode=ocr_mode,
            enrich=enrich,
            parallel=parallel,
        )
        all_results.extend(results)
    return {"results": all_results, "telemetry": {}}


@router.post("/export/xlsx", status_code=status.HTTP_200_OK)
async def export_xlsx(
    pdf: UploadFile = File(...),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(True),
    parallel: int = Form(2),
    handler=Depends(get_extract_handler),
) -> FileResponse:
    from dobs.presentation.export.excel import export_workbook

    pdf_path, txt_path = _persist_uploads(pdf, txt)
    results = await handler(
        pdf_path=pdf_path,
        txt_path=txt_path,
        backend=backend or None,
        tier=tier or None,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
    )
    out_dir = Path(tempfile.mkdtemp(prefix="dobs_xlsx_"))
    out_file = out_dir / f"{pdf.filename or 'statement'}.xlsx"
    export_workbook(results, out_file)
    return FileResponse(
        str(out_file),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out_file.name,
    )
