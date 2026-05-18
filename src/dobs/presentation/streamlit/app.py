from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import streamlit as st

from dobs.presentation.streamlit.client import ApiClient
from dobs.presentation.streamlit.components.styles import inject_styles
from dobs.presentation.streamlit.components.toolbar import render_toolbar
from dobs.presentation.streamlit.presenters.audit_presenter import AuditPresenter
from dobs.presentation.streamlit.presenters.extraction_presenter import ExtractionPresenter
from dobs.presentation.streamlit.presenters.review_presenter import ReviewPresenter
from dobs.presentation.streamlit.state import SessionState

st.set_page_config(page_title="dobs.ai — Statement Extractor", page_icon=":bank:", layout="wide")
inject_styles()


def main() -> None:
    state = SessionState()
    client = ApiClient(os.getenv("DOBS_API_URL", "http://localhost:8000"))
    render_toolbar(state, client)
    page = st.sidebar.radio("Page", ["Extract", "Review", "Audit"], label_visibility="collapsed")
    if page == "Extract":
        ExtractionPresenter(client, state).render()
    elif page == "Review":
        ReviewPresenter(client, state).render()
    else:
        AuditPresenter(client, state).render()


def run() -> None:
    import subprocess
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", __file__, "--server.headless", "true"],
        close_fds=True,
    )


main()
