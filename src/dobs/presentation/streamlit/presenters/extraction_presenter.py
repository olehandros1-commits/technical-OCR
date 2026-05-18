from __future__ import annotations

import json
import time

import requests
import streamlit as st

from dobs.presentation.streamlit.client import ApiClient
from dobs.presentation.streamlit.components.file_dropzone import render_file_uploader
from dobs.presentation.streamlit.components.pipeline_events import render_pipeline_events
from dobs.presentation.streamlit.state import SessionState


class ExtractionPresenter:
    def __init__(self, client: ApiClient, state: SessionState) -> None:
        self._client = client
        self._state = state

    def render(self) -> None:
        st.title("Bank Statement Extractor")
        st.caption(
            "Drop one or several bank-statement PDFs. "
            "The pipeline streams progress live and returns reconciled structured JSON."
        )

        inputs, _ = render_file_uploader()

        go = st.button(
            f":arrow_forward: Run extraction on {len(inputs)} file(s)"
            if inputs
            else ":arrow_forward: Run extraction (upload a PDF first)",
            type="primary",
            disabled=not inputs,
            use_container_width=True,
        )

        if go and inputs:
            self._run_extraction(inputs)

    def _run_extraction(self, inputs: list[tuple[bytes, str, bytes | None, str]]) -> None:
        progress_placeholder = st.container().empty()
        log_lines: list[str] = []
        all_results: dict[str, list[dict]] = {}

        for pdf_bytes, pdf_name, _txt_bytes, _txt_name in inputs:
            log_lines.append(f"\n### Processing **{pdf_name}**")
            render_pipeline_events(log_lines, progress_placeholder)
            try:
                with st.spinner(f"{pdf_name}: running pipeline…"):
                    results = self._stream_extract(pdf_bytes, pdf_name, log_lines, progress_placeholder)
            except Exception as exc:
                st.error(f"{pdf_name}: {exc}")
                results = []
            all_results[pdf_name] = results

        self._state.telemetry = self._client.get_telemetry()
        self._state.results_by_file = all_results
        self._state.review_threshold = self._state.review_threshold

    def _stream_extract(
        self,
        pdf_bytes: bytes,
        pdf_name: str,
        log_lines: list[str],
        placeholder,
    ) -> list[dict]:
        job_id = self._client.create_job(
            pdf_bytes, pdf_name,
            self._state.tier, self._state.enrich, self._state.parallel,
        )
        log_lines.append(f"`queued` job **{job_id[:8]}…**")
        render_pipeline_events(log_lines, placeholder)

        t0 = time.time()
        try:
            for raw in self._client.stream_job_events(job_id):
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                try:
                    msg = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                elapsed = f"{time.time() - t0:6.2f}s"
                evt = msg.get("event", "")
                data = msg.get("data", {})
                log_lines.append(f"`{elapsed}` **{evt}** {data}")
                render_pipeline_events(log_lines, placeholder)
                if evt == "done":
                    break
        except requests.exceptions.Timeout:
            log_lines.append("`timeout` SSE stream timed out — polling for result")
            render_pipeline_events(log_lines, placeholder)

        return self._client.poll_job(job_id)
