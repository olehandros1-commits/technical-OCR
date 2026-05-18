from __future__ import annotations

import streamlit as st

from dobs.presentation.streamlit.client import ApiClient
from dobs.presentation.streamlit.state import SessionState


def render_toolbar(state: SessionState, client: ApiClient) -> None:
    st.sidebar.title(":bank: dobs.ai")
    st.sidebar.markdown("**Bank Statement Extractor**")

    tiers = client.get_tiers()
    tier_options = ["(default)"] + tiers
    raw_tier = st.sidebar.selectbox("Tier", tier_options, index=0)
    state.tier = "" if raw_tier == "(default)" else raw_tier

    state.enrich = st.sidebar.toggle("Enrich (category + confidence)", value=True)
    state.review_threshold = st.sidebar.slider(
        "Review threshold (confidence below = needs human)", 0.0, 1.0, 0.5, 0.05
    )
    state.parallel = st.sidebar.slider("Parallel statements", 1, 6, 2)

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Pipeline: ingest → segment → summary → transactions → "
        "reconcile → repair → enrich → anomaly → HITL."
    )
