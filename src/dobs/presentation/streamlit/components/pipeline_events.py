from __future__ import annotations

import streamlit as st


def render_pipeline_events(events: list[str], placeholder=None) -> None:
    content = "\n\n".join(events[-60:])
    if placeholder is not None:
        placeholder.markdown(content)
    else:
        st.markdown(content)
