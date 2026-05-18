from __future__ import annotations

import io
import os
import time
from collections.abc import Generator
from typing import Any

import requests


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        self._headers = self._build_headers()

    def _build_headers(self) -> dict[str, str]:
        key = os.getenv("EXTRACTOR_API_KEYS", "")
        first = next((k.strip() for k in key.split(",") if k.strip()), "")
        return {"x-api-key": first} if first else {}

    def get_tiers(self) -> list[str]:
        try:
            r = requests.get(
                f"{self._base}/api/v1/telemetry/tiers",
                headers=self._headers,
                timeout=4,
            )
            r.raise_for_status()
            return [t.get("name", t.get("id", "")) for t in r.json().get("tiers", [])]
        except Exception:
            return []

    def create_job(
        self, pdf_bytes: bytes, pdf_name: str, tier: str, enrich: bool, parallel: int
    ) -> str:
        r = requests.post(
            f"{self._base}/api/v1/extraction/jobs",
            headers=self._headers,
            files={"pdf": (pdf_name, io.BytesIO(pdf_bytes), "application/pdf")},
            data={"tier": tier, "enrich": str(enrich).lower(), "parallel": str(parallel)},
            timeout=30,
        )
        r.raise_for_status()
        return str(r.json()["job_id"])

    def stream_job_events(self, job_id: str) -> Generator[bytes, None, None]:
        with requests.get(
            f"{self._base}/api/v1/extraction/jobs/{job_id}/events",
            headers=self._headers,
            stream=True,
            timeout=300,
        ) as sse:
            yield from sse.iter_lines()

    def poll_job(self, job_id: str, max_wait: int = 120) -> list[dict[str, Any]]:
        for _ in range(max_wait // 2):
            r = requests.get(
                f"{self._base}/api/v1/extraction/jobs/{job_id}",
                headers=self._headers,
                timeout=10,
            )
            r.raise_for_status()
            body = r.json()
            if body.get("done"):
                if body.get("error"):
                    raise RuntimeError(body["error"])
                return body.get("results") or []
            time.sleep(2)
        raise TimeoutError(f"Job {job_id} did not complete within {max_wait}s")

    def get_telemetry(self) -> dict[str, Any]:
        try:
            r = requests.get(f"{self._base}/api/v1/telemetry", headers=self._headers, timeout=5)
            r.raise_for_status()
            result: dict[str, Any] = r.json()
            return result
        except Exception:
            return {}

    def get_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            r = requests.get(
                f"{self._base}/api/v1/audit",
                headers=self._headers,
                params={"limit": limit},
                timeout=5,
            )
            r.raise_for_status()
            result: list[dict[str, Any]] = r.json()
            return result
        except Exception:
            return []

    def post_review(self, statement_key: str, tx_index: int, decision: str) -> None:
        try:
            requests.post(
                f"{self._base}/api/v1/reviews",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"statement_key": statement_key, "tx_index": tx_index, "decision": decision},
                timeout=5,
            )
        except Exception:
            pass

    def explain_anomaly(self, anomaly: dict[str, Any], transaction: dict[str, Any] | None) -> str:
        try:
            r = requests.post(
                f"{self._base}/api/v1/reviews/explain",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"anomaly": anomaly, "transaction": transaction},
                timeout=15,
            )
            r.raise_for_status()
            return str(r.json().get("explanation", r.text))
        except Exception as exc:
            return f"Could not fetch explanation: {exc}"

    def export_xlsx(
        self, pdf_bytes: bytes, pdf_name: str, tier: str, enrich: bool, parallel: int
    ) -> bytes:
        r = requests.post(
            f"{self._base}/api/v1/extraction/export/xlsx",
            headers=self._headers,
            files={"pdf": (pdf_name, io.BytesIO(pdf_bytes), "application/pdf")},
            data={"tier": tier, "enrich": str(enrich).lower(), "parallel": str(parallel)},
            timeout=120,
        )
        r.raise_for_status()
        return r.content
