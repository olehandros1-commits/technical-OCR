"""Streamlit UI re-export shim.

The Streamlit UI is a single-file module that predates the clean-arch
refactor. Refactoring it is deferred to a later phase. This module
re-exports everything from the legacy src/extractor/ui_streamlit.py so
that the presentation package boundary is respected without duplicating
the implementation.

Run with:
    streamlit run src/dobs/presentation/streamlit/app.py
"""
from extractor.ui_streamlit import *  # noqa: F401, F403
