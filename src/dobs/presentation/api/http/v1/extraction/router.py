from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.application.dto.serializers import serialize_results
from dobs.application.ports.job_queue import JobStorePort
from dobs.infrastructure.adapters.event_bus.context_event_bus import bind_event_bus
from dobs.infrastructure.adapters.event_bus.store_event_bus import StoreEventBus
from dobs.infrastructure.adapters.jobs.background_runner import BackgroundJobRunner
from dobs.infrastructure.adapters.replay.replaying_extract_handler import ReplayingExtractHandler
from dobs.main.logging_setup import get_logger
from dobs.presentation.api.http.middleware.api_key import api_key_dependency
from dobs.presentation.api.http.middleware.tenant import current_tenant
from dobs.presentation.api.http.v1.extraction.schemas import (
    ExtractResponse,
    JobCreatedResponse,
    JobResultResponse,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/extraction",
    tags=["extraction"],
    route_class=DishkaRoute,
    dependencies=[Depends(api_key_dependency)],
)


def _upload_root() -> Path:
    root = Path(os.getenv("DOBS_UPLOAD_ROOT", "out/uploads"))
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _persist_uploads(
    pdf: UploadFile | None,
    txt: UploadFile | None,
) -> tuple[Path | None, Path | None]:
    if pdf is None and txt is None:
        raise HTTPException(status_code=422, detail="Provide at least one of: pdf, txt")
    tmp = _upload_root() / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)
    pdf_path: Path | None = None
    if pdf is not None:
        pdf_path = tmp / (pdf.filename or "upload.pdf")
        async with aiofiles.open(pdf_path, "wb") as f:
            await f.write(await pdf.read())
    txt_path: Path | None = None
    if txt is not None:
        txt_path = tmp / (txt.filename or "upload.txt")
        async with aiofiles.open(txt_path, "wb") as f:
            await f.write(await txt.read())
    return pdf_path, txt_path


def _build_command(
    *,
    pdf_path: Path | None,
    txt_path: Path | None,
    tier: str,
    ocr_mode: str,
    enrich: bool,
    parallel: int,
    tenant: str,
) -> ExtractStatementCommand:
    return ExtractStatementCommand(
        pdf_path=str(pdf_path) if pdf_path else None,
        txt_path=str(txt_path) if txt_path else None,
        tier=tier or None,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        tenant=tenant,
    )


@router.post("/extract", status_code=status.HTTP_200_OK, response_model=ExtractResponse)
async def extract(
    handler: FromDishka[ReplayingExtractHandler],
    pdf: UploadFile | None = File(None),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> ExtractResponse:
    pdf_path, txt_path = await _persist_uploads(pdf, txt)
    command = _build_command(
        pdf_path=pdf_path,
        txt_path=txt_path,
        tier=tier,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        tenant=current_tenant(),
    )
    results = await handler(command)
    return ExtractResponse(results=serialize_results(results), telemetry={})


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreatedResponse)
async def create_job(
    handler: FromDishka[ReplayingExtractHandler],
    store: FromDishka[JobStorePort],
    runner: FromDishka[BackgroundJobRunner],
    pdf: UploadFile | None = File(None),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> JobCreatedResponse:
    pdf_path, txt_path = await _persist_uploads(pdf, txt)
    job_id = str(uuid.uuid4())
    tenant = current_tenant()
    command = _build_command(
        pdf_path=pdf_path,
        txt_path=txt_path,
        tier=tier,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        tenant=tenant,
    )

    redis_url = os.getenv("REDIS_URL")
    await store.write_event(job_id, {"event": "queued", "data": {}})

    if redis_url:
        from dobs.infrastructure.adapters.jobs.arq_job_queue import ArqJobQueue

        queue = ArqJobQueue(redis_url=redis_url)
        await queue.enqueue(job_id, command)
        log.info("job enqueued to arq", job_id=job_id, tenant=tenant, tier=tier)
        return JobCreatedResponse(job_id=job_id)

    async def _run() -> None:
        bus = StoreEventBus(store=store, job_id=job_id)
        try:
            with bind_event_bus(bus):
                results = await handler(command)
            await store.write_result(job_id, result=serialize_results(results))
            log.info("job done in-process", job_id=job_id)
        except Exception as exc:
            log.exception("job failed in-process", job_id=job_id)
            await store.write_result(job_id, error=str(exc))

    runner.spawn(_run, name=f"extract-{job_id}")
    return JobCreatedResponse(job_id=job_id)


_SSE_HEARTBEAT_S = float(os.getenv("DOBS_SSE_HEARTBEAT_S", "15"))


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    store: FromDishka[JobStorePort],
) -> StreamingResponse:
    import asyncio

    if not await store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def _stream() -> AsyncIterator[str]:
        events_iter = store.read_events(job_id).__aiter__()
        while True:
            next_task = asyncio.ensure_future(events_iter.__anext__())
            try:
                event = await asyncio.wait_for(next_task, timeout=_SSE_HEARTBEAT_S)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            except StopAsyncIteration:
                return
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("event") == "done":
                return

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/jobs/{job_id}", response_model=JobResultResponse)
async def get_job(
    job_id: str,
    store: FromDishka[JobStorePort],
) -> JobResultResponse:
    result, error, done = await store.read_result(job_id)
    if result is None and error == "Job not found":
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResultResponse(job_id=job_id, done=done, results=result, error=error)


@router.post("/extract/bulk", status_code=status.HTTP_200_OK)
async def extract_bulk(
    handler: FromDishka[ReplayingExtractHandler],
    files: list[UploadFile] = File(...),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> dict[str, object]:
    all_results: list[dict[str, object]] = []
    tenant = current_tenant()
    for upload in files:
        tmp = _upload_root() / uuid.uuid4().hex
        tmp.mkdir(parents=True, exist_ok=True)
        pdf_path = tmp / (upload.filename or "upload.pdf")
        async with aiofiles.open(pdf_path, "wb") as f:
            await f.write(await upload.read())
        command = _build_command(
            pdf_path=pdf_path,
            txt_path=None,
            tier=tier,
            ocr_mode=ocr_mode,
            enrich=enrich,
            parallel=parallel,
            tenant=tenant,
        )
        results = await handler(command)
        all_results.extend(serialize_results(results))
    return {"results": all_results, "telemetry": {}}


@router.post("/export/xlsx", status_code=status.HTTP_200_OK)
async def export_xlsx(
    handler: FromDishka[ReplayingExtractHandler],
    pdf: UploadFile | None = File(None),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(True),
    parallel: int = Form(2),
) -> FileResponse:
    from dobs.presentation.export.excel import export_workbook

    pdf_path, txt_path = await _persist_uploads(pdf, txt)
    command = _build_command(
        pdf_path=pdf_path,
        txt_path=txt_path,
        tier=tier,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        tenant=current_tenant(),
    )
    results = await handler(command)
    out_dir = _upload_root() / "xlsx" / uuid.uuid4().hex
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = (pdf.filename if pdf else None) or (txt.filename if txt else None) or "statement"
    out_file = out_dir / f"{base_name}.xlsx"
    export_workbook(serialize_results(results), out_file)
    return FileResponse(
        str(out_file),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out_file.name,
    )
