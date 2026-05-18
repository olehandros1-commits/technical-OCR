from __future__ import annotations

import streamlit as st


class SessionState:
    @property
    def results_by_file(self) -> dict[str, list[dict]]:
        return st.session_state.get("results_by_file", {})

    @results_by_file.setter
    def results_by_file(self, value: dict[str, list[dict]]) -> None:
        st.session_state["results_by_file"] = value

    @property
    def telemetry(self) -> dict:
        return st.session_state.get("telemetry", {})

    @telemetry.setter
    def telemetry(self, value: dict) -> None:
        st.session_state["telemetry"] = value

    @property
    def review_threshold(self) -> float:
        return st.session_state.get("review_threshold", 0.5)

    @review_threshold.setter
    def review_threshold(self, value: float) -> None:
        st.session_state["review_threshold"] = value

    @property
    def tier(self) -> str:
        return st.session_state.get("tier", "")

    @tier.setter
    def tier(self, value: str) -> None:
        st.session_state["tier"] = value

    @property
    def enrich(self) -> bool:
        return st.session_state.get("enrich", True)

    @enrich.setter
    def enrich(self, value: bool) -> None:
        st.session_state["enrich"] = value

    @property
    def parallel(self) -> int:
        return st.session_state.get("parallel", 2)

    @parallel.setter
    def parallel(self, value: int) -> None:
        st.session_state["parallel"] = value

    @property
    def api_base(self) -> str:
        return st.session_state.get("api_base", "http://localhost:8000")

    @api_base.setter
    def api_base(self, value: str) -> None:
        st.session_state["api_base"] = value
