"""Convenience client wrapper around the generated gRPC stubs.

Most callers want one of:
    from extractor.grpc.client import extract, extract_streaming

Both return native Python dicts / iterators; the protobuf surface is an
implementation detail.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


def _connect(target: str | None = None):
    from extractor.grpc.server import _ensure_codegen
    pb, pb_grpc = _ensure_codegen()
    import grpc
    target = target or os.getenv("GRPC_TARGET", "localhost:50051")
    msg_max = 200 * 1024 * 1024  # match the server-side limit
    channel = grpc.insecure_channel(target, options=[
        ("grpc.max_receive_message_length", msg_max),
        ("grpc.max_send_message_length", msg_max),
    ])
    return pb, pb_grpc, channel


def extract(
    pdf_path: str | Path,
    txt_path: str | Path | None = None,
    *,
    backend: str = "anthropic",
    ocr_mode: str = "auto",
    enrich: bool = True,
    parallel: int = 2,
    target: str | None = None,
) -> dict:
    pb, pb_grpc, channel = _connect(target)
    stub = pb_grpc.ExtractorServiceStub(channel)
    req = pb.ExtractRequest(
        filename=Path(pdf_path).name,
        payload=Path(pdf_path).read_bytes(),
        txt_payload=Path(txt_path).read_bytes() if txt_path else b"",
        backend=backend, ocr_mode=ocr_mode, enrich=enrich, parallel=parallel,
    )
    resp = stub.Extract(req)
    return {
        "results": json.loads(resp.results_json or "[]"),
        "telemetry": json.loads(resp.telemetry_json or "{}"),
    }


def extract_streaming(
    pdf_path: str | Path,
    txt_path: str | Path | None = None,
    *,
    backend: str = "anthropic",
    ocr_mode: str = "auto",
    enrich: bool = True,
    parallel: int = 2,
    target: str | None = None,
) -> Iterator[dict]:
    pb, pb_grpc, channel = _connect(target)
    stub = pb_grpc.ExtractorServiceStub(channel)
    req = pb.ExtractRequest(
        filename=Path(pdf_path).name,
        payload=Path(pdf_path).read_bytes(),
        txt_payload=Path(txt_path).read_bytes() if txt_path else b"",
        backend=backend, ocr_mode=ocr_mode, enrich=enrich, parallel=parallel,
    )
    for ev in stub.StreamExtract(req):
        record = {
            "event": ev.event_name,
            "data": json.loads(ev.data_json or "{}"),
            "ts": ev.ts_unix,
        }
        if ev.is_terminal and ev.HasField("final"):
            record["final"] = {
                "results": json.loads(ev.final.results_json or "[]"),
                "telemetry": json.loads(ev.final.telemetry_json or "{}"),
            }
        yield record
