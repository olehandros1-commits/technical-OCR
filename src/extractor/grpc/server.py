"""gRPC adapter over the pipeline.

Same business logic as the REST API -- thin shim around `extract_all`.
Use this transport for service-to-service calls (typed schema, HTTP/2
multiplexing, streaming response over a single connection).

Run with:
    python -m extractor.grpc.server          # listens on :50051
or programmatically:
    from extractor.grpc.server import serve; serve()

The stubs are generated lazily from extractor.proto via grpc_tools on
first import (so you don't have to remember to run a codegen step).
"""
from __future__ import annotations
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import time
from concurrent import futures
from pathlib import Path

log = logging.getLogger(__name__)

_PROTO = Path(__file__).parent / "extractor.proto"
_GEN_DIR = Path(__file__).parent


def _ensure_codegen() -> tuple[object, object]:
    """Generate extractor_pb2 / extractor_pb2_grpc if missing, then import."""
    pb_file = _GEN_DIR / "extractor_pb2.py"
    grpc_file = _GEN_DIR / "extractor_pb2_grpc.py"
    if not pb_file.exists() or not grpc_file.exists():
        from grpc_tools import protoc
        ret = protoc.main([
            "protoc",
            f"-I{_GEN_DIR}",
            f"--python_out={_GEN_DIR}",
            f"--grpc_python_out={_GEN_DIR}",
            str(_PROTO),
        ])
        if ret != 0:
            raise RuntimeError(f"protoc codegen failed (rc={ret})")
    sys.path.insert(0, str(_GEN_DIR))
    import extractor_pb2 as pb  # type: ignore
    import extractor_pb2_grpc as pb_grpc  # type: ignore
    return pb, pb_grpc


def serve(port: int = 50051) -> None:
    import grpc
    pb, pb_grpc = _ensure_codegen()
    from extractor.pipeline import extract_all
    from extractor.telemetry import TelemetryCollector, set_collector, get_collector

    class ExtractorService(pb_grpc.ExtractorServiceServicer):
        def Health(self, request, context):
            return pb.HealthResponse(
                ok=True, service="bank-statement-extractor", version="0.3.0",
            )

        def _persist(self, req) -> tuple[Path, Path | None]:
            tmp = Path(tempfile.mkdtemp(prefix="bse_grpc_"))
            pdf_path = tmp / (req.filename or "upload.bin")
            pdf_path.write_bytes(req.payload)
            txt_path: Path | None = None
            if req.txt_payload:
                txt_path = tmp / (Path(req.filename or "upload").stem + ".txt")
                txt_path.write_bytes(req.txt_payload)
            return pdf_path, txt_path

        def Extract(self, request, context):
            pdf_path, txt_path = self._persist(request)
            set_collector(TelemetryCollector())
            try:
                results = extract_all(
                    str(pdf_path),
                    str(txt_path) if txt_path else None,
                    backend=request.backend or "anthropic",
                    ocr_mode=request.ocr_mode or "auto",
                    enrich=bool(request.enrich),
                    parallel=int(request.parallel) or 2,
                )
            except Exception as e:
                context.set_details(str(e))
                context.set_code(grpc.StatusCode.INTERNAL)
                return pb.ExtractResponse()
            return pb.ExtractResponse(
                results_json=json.dumps(results),
                telemetry_json=json.dumps(get_collector().summary()),
            )

        def StreamExtract(self, request, context):
            pdf_path, txt_path = self._persist(request)
            set_collector(TelemetryCollector())
            event_q: queue.Queue = queue.Queue()
            done = threading.Event()
            result_holder: dict = {}

            def log_event(name: str, data: dict) -> None:
                event_q.put((name, data, False))

            def worker():
                try:
                    result_holder["results"] = extract_all(
                        str(pdf_path),
                        str(txt_path) if txt_path else None,
                        backend=request.backend or "anthropic",
                        ocr_mode=request.ocr_mode or "auto",
                        enrich=bool(request.enrich),
                        parallel=int(request.parallel) or 2,
                        log_event=log_event,
                    )
                except Exception as e:
                    event_q.put(("error", {"error": str(e)}, False))
                finally:
                    done.set()
                    event_q.put(("done", {}, True))

            threading.Thread(target=worker, daemon=True).start()
            while True:
                name, data, terminal = event_q.get()
                ev = pb.ProgressEvent(
                    event_name=name,
                    data_json=json.dumps(data),
                    ts_unix=time.time(),
                    is_terminal=terminal,
                )
                if terminal:
                    results = result_holder.get("results", [])
                    ev.final.CopyFrom(pb.ExtractResponse(
                        results_json=json.dumps(results),
                        telemetry_json=json.dumps(get_collector().summary()),
                    ))
                yield ev
                if terminal:
                    return

    # 200 MB is plenty for the largest realistic statement PDF.
    msg_max = 200 * 1024 * 1024
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=8),
        options=[
            ("grpc.max_receive_message_length", msg_max),
            ("grpc.max_send_message_length", msg_max),
        ],
    )
    pb_grpc.add_ExtractorServiceServicer_to_server(ExtractorService(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    log.info("gRPC ExtractorService listening on :%d", port)
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    port = int(os.getenv("GRPC_PORT", "50051"))
    serve(port)
