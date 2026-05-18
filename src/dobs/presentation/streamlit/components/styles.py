from __future__ import annotations

import streamlit as st

_CSS = """<style>
.reconciled-ok  { color:#16a34a; font-weight:600; }
.reconciled-bad { color:#dc2626; font-weight:600; }
.badge-info  { background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:8px; font-size:11px; margin-right:4px; }
.badge-warn  { background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:8px; font-size:11px; margin-right:4px; }
.badge-error { background:#fee2e2; color:#991b1b; padding:2px 8px; border-radius:8px; font-size:11px; margin-right:4px; }
.review-row  { background:#fafafa; border-left:3px solid #f59e0b; padding:6px 10px; margin:4px 0; border-radius:4px; }
div[data-testid="stMetricLabel"] { font-size:12px; color:#6b7280; }
</style>"""


def inject_styles() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
