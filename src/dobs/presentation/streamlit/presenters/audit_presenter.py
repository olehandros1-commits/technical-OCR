from __future__ import annotations

import pandas as pd
import streamlit as st

from dobs.presentation.streamlit.client import ApiClient
from dobs.presentation.streamlit.state import SessionState


class AuditPresenter:
    def __init__(self, client: ApiClient, state: SessionState) -> None:
        self._client = client
        self._state = state

    def render(self) -> None:
        st.title("Audit & Telemetry")

        st.markdown("### Telemetry")
        tel = self._client.get_telemetry()
        if tel:
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("LLM calls", tel.get("total_calls", 0))
            t2.metric("Input tokens", f"{tel.get('total_input_tokens', 0):,}")
            t3.metric("Output tokens", f"{tel.get('total_output_tokens', 0):,}")
            t4.metric("Cost (USD)", f"${tel.get('total_cost_usd', 0):.4f}")
        else:
            st.info("No telemetry data available.")

        st.markdown("### Audit Log")
        limit = st.number_input("Entries to fetch", min_value=10, max_value=1000, value=100, step=10)
        records = self._client.get_audit(int(limit))
        if records:
            st.dataframe(pd.DataFrame(records), use_container_width=True)
        else:
            st.info("No audit records found.")
