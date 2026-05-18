from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import uuid
from pathlib import Path

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.infrastructure.adapters.event_bus.store_event_bus import StoreEventBus
from dobs.infrastructure.adapters.jobs.memory_job_store import MemoryJobStore
from dobs.main.di import _ReplayingExtractHandler
from dobs.presentation.api.http.middleware.api_key import api_key_dependency
from dobs.presentation.api.http.middleware.tenant import current_tenant
from dobs.presentation.api.http.v1.extraction.schemas import (
    ExtractResponse,
    JobCreatedResponse,
    JobResultResponse,
)

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


def _persist_uploads(
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
        pdf_path.write_bytes(pdf.file.read())
    txt_path: Path | None = None
    if txt is not None:
        txt_path = tmp / (txt.filename or "upload.txt")
        txt_path.write_bytes(txt.file.read())
    return pdf_path, txt_path


def _serialize_results(results: list) -> list[dict]:
    if not results:
        return []
    if isinstance(results[0], dict):
        return results
    return [dataclasses.asdict(r) for r in results]


_memory_store = MemoryJobStore()


def _get_store():
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        from dobs.infrastructure.adapters.jobs.redis_job_store import RedisJobStore
        return RedisJobStore(url=redis_url)
    return _memory_store


@router.post("/extract", status_code=status.HTTP_200_OK, response_model=ExtractResponse)
async def extract(
    handler: FromDishka[_ReplayingExtractHandler],
    pdf: UploadFile | None = File(None),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> ExtractResponse:
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    command = ExtractStatementCommand(
        pdf_path=str(pdf_path) if pdf_path else None,
        txt_path=str(txt_path) if txt_path else None,
        tier=tier or None,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        tenant=current_tenant(),
    )
    results = await handler(command)
    return ExtractResponse(results=_serialize_results(results), telemetry={})


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreatedResponse)
async def create_job(
    pdf: UploadFile | None = File(None),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> JobCreatedResponse:
    pdf_path, txt_path = _persist_uploads(pdf, txt)
    job_id = str(uuid.uuid4())
    tenant = current_tenant()
    store = _get_store()

    command = ExtractStatementCommand(
        pdf_path=str(pdf_path) if pdf_path else None,
        txt_path=str(txt_path) if txt_path else None,
        tier=tier or None,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
        tenant=tenant,
    )

    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        from dobs.infrastructure.adapters.jobs.arq_job_queue import ArqJobQueue
        queue = ArqJobQueue(redis_url=redis_url)
        await store.write_event(job_id, {"event": "queued", "data": {}})
        await queue.enqueue(job_id, command)
    else:
        await store.write_event(job_id, {"event": "queued", "data": {}})

        async def _run_inprocess() -> None:
            from dishka import make_async_container

            from dobs.main.di import build_providers

            local_container = make_async_container(*build_providers())
            try:
                async with local_container() as request_scope:
                    inner = await request_scope.get(_ReplayingExtractHandler)
                    inner._event_bus = StoreEventBus(store=store, job_id=job_id)
                    try:
                        results = await inner(command)
                        await store.write_result(job_id, result=_serialize_results(results))
                    except Exception as exc:
                        await store.write_result(job_id, error=str(exc))
            finally:
                await local_container.close()

        asyncio.create_task(_run_inprocess())

    return JobCreatedResponse(job_id=job_id)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    store = _get_store()
    if not await store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    async def _stream():
        async for event in store.read_events(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/jobs/{job_id}", response_model=JobResultResponse)
async def get_job(job_id: str) -> JobResultResponse:
    store = _get_store()
    result, error, done = await store.read_result(job_id)
    if result is None and error == "Job not found":
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResultResponse(job_id=job_id, done=done, results=result, error=error)


@router.post("/extract/bulk", status_code=status.HTTP_200_OK)
async def extract_bulk(
    handler: FromDishka[_ReplayingExtractHandler],
    files: list[UploadFile] = File(...),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(False),
    parallel: int = Form(2),
) -> dict:
    all_results: list[dict] = []
    tenant = current_tenant()
    for upload in files:
        tmp = _upload_root() / uuid.uuid4().hex
        tmp.mkdir(parents=True, exist_ok=True)
        pdf_path = tmp / (upload.filename or "upload.pdf")
        pdf_path.write_bytes(upload.file.read())
        command = ExtractStatementCommand(
            pdf_path=str(pdf_path),
            txt_path=None,
            tier=tier or None,
            ocr_mode=ocr_mode,
            enrich=enrich,
            parallel=parallel,
            tenant=tenant,
        )
        results = await handler(command)
        all_results.extend(_serialize_results(results))
    return {"results": all_results, "telemetry": {}}


@router.post("/export/xlsx", status_code=status.HTTP_200_OK)
async def export_xlsx(
    handler: FromDishka[_ReplayingExtractHandler],
    pdf: UploadFile | None = File(None),
    txt: UploadFile | None = File(None),
    backend: str = Form(""),
    tier: str = Form(""),
    ocr_mode: str = Form("auto"),
    enrich: bool = Form(True),
    parallel: int = Form(2),
) -> FileResponse:
    from dobs.presentation.export.excel import export_workbook

    pdf_path, txt_path = _persist_uploads(pdf, txt)
    command = ExtractStatementCommand(
        pdf_path=str(pdf_path) if pdf_path else None,
        txt_path=str(txt_path) if txt_path else None,
        tier=tier or None,
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
    export_workbook(_serialize_results(results), out_file)
    return FileResponse(
        str(out_file),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out_file.name,
    )
