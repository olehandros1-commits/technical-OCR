from __future__ import annotations

from typing import Any

import streamlit as st


class SessionState:
    @property
    def results_by_file(self) -> dict[str, list[dict[str, Any]]]:
        return st.session_state.get("results_by_file", {})  # type: ignore[no-any-return]  # streamlit Any

    @results_by_file.setter
    def results_by_file(self, value: dict[str, list[dict[str, Any]]]) -> None:
        st.session_state["results_by_file"] = value

    @property
    def telemetry(self) -> dict[str, Any]:
        return st.session_state.get("telemetry", {})  # type: ignore[no-any-return]  # streamlit Any

    @telemetry.setter
    def telemetry(self, value: dict[str, Any]) -> None:
        st.session_state["telemetry"] = value

    @property
    def review_threshold(self) -> float:
        return float(st.session_state.get("review_threshold", 0.5))

    @review_threshold.setter
    def review_threshold(self, value: float) -> None:
        st.session_state["review_threshold"] = value

    @property
    def tier(self) -> str:
        return str(st.session_state.get("tier", ""))

    @tier.setter
    def tier(self, value: str) -> None:
        st.session_state["tier"] = value

    @property
    def enrich(self) -> bool:
        return bool(st.session_state.get("enrich", True))

    @enrich.setter
    def enrich(self, value: bool) -> None:
        st.session_state["enrich"] = value

    @property
    def parallel(self) -> int:
        return int(st.session_state.get("parallel", 2))

    @parallel.setter
    def parallel(self, value: int) -> None:
        st.session_state["parallel"] = value

    @property
    def api_base(self) -> str:
        return str(st.session_state.get("api_base", "http://localhost:8000"))

    @api_base.setter
    def api_base(self, value: str) -> None:
        st.session_state["api_base"] = value
