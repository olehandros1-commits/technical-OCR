"""Streamlit web UI for the bank statement extractor.

Run with:
    streamlit run src/extractor/ui_streamlit.py

Highlights:
  * Drag-drop ONE or MANY PDFs (batch processing).
  * Optional pre-OCR'd text file per PDF.
  * Backend toggle (Anthropic Claude vs local Ollama qwen2.5).
  * Live progress stream as the pipeline runs.
  * Per-statement reconciliation panel with deltas.
  * Filterable transactions table (category, side, confidence).
  * Anomaly badges (duplicate / out-of-period / size outlier / low conf).
  * HITL review queue: low-confidence rows surface for approve / reject /
    edit. Decisions persist in the SQLite cache.
  * Live cost / token telemetry.
  * Download buttons: JSON and CSV.
"""
from __future__ import annotations
import io
import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator

# Allow `streamlit run src/extractor/ui_streamlit.py`.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import streamlit as st  # noqa: E402
import pandas as pd  # noqa: E402

from extractor.pipeline import extract_all  # noqa: E402
from extractor.telemetry import TelemetryCollector, set_collector, get_collector  # noqa: E402


st.set_page_config(
    page_title="Bank Statement Extractor",
    page_icon=":bank:",
    layout="wide",
)

st.markdown(
    """
    <style>
    .reconciled-ok    { color: #16a34a; font-weight: 600; }
    .reconciled-bad   { color: #dc2626; font-weight: 600; }
    .badge-info  { background:#dbeafe; color:#1e40af; padding:2px 8px; border-radius:8px; font-size:11px; margin-right:4px;}
    .badge-warn  { background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:8px; font-size:11px; margin-right:4px;}
    .badge-error { background:#fee2e2; color:#991b1b; padding:2px 8px; border-radius:8px; font-size:11px; margin-right:4px;}
    .review-row  { background: #fafafa; border-left: 3px solid #f59e0b; padding: 6px 10px; margin: 4px 0; border-radius: 4px; }
    div[data-testid="stMetricLabel"] { font-size: 12px; color: #6b7280; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Sidebar -------------------------------------------------------

st.sidebar.title(":bank: Statement Extractor")
st.sidebar.markdown("**dobs.ai technical demo**")

backend_choice = st.sidebar.selectbox(
    "Backend",
    ["anthropic", "ollama"],
    index=0,
    help="Cloud Claude (Sonnet / Opus) or local Ollama (qwen2.5).",
)

enrich = st.sidebar.toggle(
    "Enrich (category + confidence)",
    value=True,
    help="One extra LLM call per statement adds category, vendor, and "
         "self-reported confidence to every transaction. Enables HITL "
         "review and richer anomaly detection.",
)

review_threshold = st.sidebar.slider(
    "Review threshold (confidence below = needs human)",
    0.0, 1.0, 0.5, 0.05,
)

parallel = st.sidebar.slider("Parallel statements", 1, 6, 2)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Pipeline: ingest -> segment -> summary -> transactions -> "
    "reconcile -> repair (adaptive) -> enrich -> anomaly -> HITL queue."
)


# ---------- File upload ---------------------------------------------------

st.title("Bank Statement Extractor")
st.caption(
    "Drop one or several bank-statement PDFs. Optionally drop the matching "
    "pre-OCR'd text files alongside. The extractor returns reconciled "
    "structured JSON plus a transactions table with confidence / category "
    "/ anomaly review queue."
)

col_pdf, col_txt = st.columns([2, 1])
with col_pdf:
    uploaded_pdfs = st.file_uploader(
        "Statement PDF(s)",
        type=["pdf"],
        accept_multiple_files=True,
    )
with col_txt:
    uploaded_txts = st.file_uploader(
        "Pre-OCR'd text file(s) (optional, match by filename stem)",
        type=["txt"],
        accept_multiple_files=True,
        help=(
            "If you upload OCR text matching a PDF (same name, .txt instead "
            "of .pdf), it will be used and the OCR stage is skipped."
        ),
    )

use_sample = st.button(":file_folder: Use bundled Ixonia sample (1 PDF)", use_container_width=True)


def _resolve_inputs() -> list[tuple[Path, Path | None, str]]:
    """Returns [(pdf_path, txt_path_or_None, label), ...]."""
    if use_sample:
        return [(ROOT / "Binder2_Redacted.pdf", ROOT / "ixonia_ocr.txt", "Ixonia (bundled)")]
    if not uploaded_pdfs:
        return []
    tmp = Path(tempfile.mkdtemp())
    # Map txt files by stem so a "chase_apr.txt" matches "chase_apr.pdf".
    txt_by_stem: dict[str, Path] = {}
    for f in (uploaded_txts or []):
        path = tmp / f.name
        path.write_bytes(f.getvalue())
        txt_by_stem[Path(f.name).stem] = path
    out: list[tuple[Path, Path | None, str]] = []
    for f in uploaded_pdfs:
        pdf_path = tmp / f.name
        pdf_path.write_bytes(f.getvalue())
        out.append((pdf_path, txt_by_stem.get(Path(f.name).stem), f.name))
    return out


inputs = _resolve_inputs()

go = st.button(
    f":arrow_forward: Run extraction on {len(inputs)} file(s)" if inputs
    else ":arrow_forward: Run extraction (upload a PDF first)",
    type="primary",
    disabled=not inputs,
    use_container_width=True,
)


def _stream_pipeline(pdf, txt, **kw) -> Iterator:
    q: queue.Queue = queue.Queue()
    result_holder: dict = {}

    def log_event(name, data):
        q.put(("event", time.time(), name, data))

    def run():
        try:
            result_holder["results"] = extract_all(
                str(pdf),
                str(txt) if txt else None,
                log_event=log_event,
                **kw,
            )
        except Exception as e:
            q.put(("error", time.time(), "fatal", str(e)))
        finally:
            q.put(("done", time.time(), "done", None))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t0 = time.time()
    while True:
        kind, ts, name, data = q.get()
        yield kind, ts - t0, name, data
        if kind == "done":
            break
    yield "result", time.time() - t0, "results", result_holder.get("results", [])


if go and inputs:
    progress_container = st.container()
    progress_log = progress_container.empty()
    log_lines: list[str] = []
    set_collector(TelemetryCollector())  # reset cost counters
    all_results_by_file: dict[str, list] = {}

    for pdf_path, txt_path, label in inputs:
        log_lines.append(f"\n### Processing **{label}**")
        progress_log.markdown("\n\n".join(log_lines[-60:]))
        with st.spinner(f"{label}: running pipeline..."):
            results = []
            for kind, elapsed, name, data in _stream_pipeline(
                pdf_path, txt_path,
                backend=backend_choice,
                enrich=enrich,
                parallel=parallel,
            ):
                if kind == "event":
                    log_lines.append(f"`{elapsed:6.2f}s` **{name}** {data}")
                    progress_log.markdown("\n\n".join(log_lines[-60:]))
                elif kind == "error":
                    st.error(f"{label}: {data}")
                elif kind == "result":
                    results = data
            all_results_by_file[label] = results

    st.session_state["results_by_file"] = all_results_by_file
    st.session_state["backend"] = backend_choice
    st.session_state["review_threshold"] = review_threshold


# ---------- Render --------------------------------------------------------

results_by_file: dict = st.session_state.get("results_by_file", {})
if not results_by_file:
    st.info(
        "Upload a PDF (or use the bundled sample) and click Run. "
        "The pipeline streams progress live."
    )
    st.stop()


# Telemetry strip
tel = get_collector().summary()
if tel.get("total_calls", 0) > 0:
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("LLM calls", tel["total_calls"])
    t2.metric("Input tokens", f"{tel['total_input_tokens']:,}")
    t3.metric("Output tokens", f"{tel['total_output_tokens']:,}")
    t4.metric("Cost (USD)", f"${tel['total_cost_usd']:.4f}")

st.markdown("---")
file_tabs = st.tabs(list(results_by_file.keys()))
for file_label, file_tab in zip(results_by_file.keys(), file_tabs):
    results = results_by_file[file_label]
    with file_tab:
        if not results:
            st.warning(f"No statements extracted from {file_label}.")
            continue

        # Aggregate metrics for this file
        total_tx = sum(len(r["transactions"]) for r in results)
        ok = sum(1 for r in results if r.get("_reconciliation", {}).get("ok"))
        total_anom = sum(len(r.get("_anomalies", [])) for r in results)

        # HITL queue: low-confidence + anomaly-flagged rows across all stmts
        review_queue = []
        for s_idx, r in enumerate(results):
            for t_idx, t in enumerate(r["transactions"]):
                conf = t.get("confidence")
                if conf is not None and conf < review_threshold:
                    review_queue.append({
                        "stmt_idx": s_idx,
                        "tx_idx": t_idx,
                        "period": r["account"]["period"]["start"],
                        "date": t["date"],
                        "description": t["description"],
                        "amount": t.get("deposit") or t.get("withdrawal"),
                        "side": "deposit" if t.get("deposit") else "withdrawal",
                        "confidence": conf,
                        "reason": f"low confidence ({conf:.2f})",
                    })
            for an in r.get("_anomalies", []):
                if an["severity"] in ("warn", "error") and an.get("transaction_index") is not None:
                    t = r["transactions"][an["transaction_index"]]
                    review_queue.append({
                        "stmt_idx": s_idx,
                        "tx_idx": an["transaction_index"],
                        "period": r["account"]["period"]["start"],
                        "date": t["date"],
                        "description": t["description"],
                        "amount": t.get("deposit") or t.get("withdrawal"),
                        "side": "deposit" if t.get("deposit") else "withdrawal",
                        "confidence": t.get("confidence"),
                        "reason": f"{an['kind']}: {an['message']}",
                    })

        # File-level metric strip
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Statements", len(results))
        m2.metric("Reconciled", f"{ok}/{len(results)}")
        m3.metric("Transactions", total_tx)
        m4.metric("Need review", len(review_queue))

        # HITL queue (if any)
        if review_queue:
            with st.expander(f":raising_hand: Human review queue ({len(review_queue)} items)", expanded=True):
                for i, item in enumerate(review_queue[:30]):  # cap rendering
                    cols = st.columns([3, 1, 1, 2])
                    cols[0].markdown(
                        f"<div class='review-row'><b>{item['date']}</b> · "
                        f"{item['description'][:80]}<br>"
                        f"<small>{item['reason']}</small></div>",
                        unsafe_allow_html=True,
                    )
                    cols[1].write(f"${item['amount']:,.2f} {item['side'][0].upper()}")
                    cols[2].button("Approve", key=f"approve-{file_label}-{i}")
                    cols[3].button("Reject / fix later", key=f"reject-{file_label}-{i}")
                if len(review_queue) > 30:
                    st.caption(f"...and {len(review_queue) - 30} more")

        # Per-statement details
        st.markdown("### Statements")
        stmt_tabs = st.tabs([
            f"{r['account']['period']['start']}  ({r['account']['account_last4']})"
            for r in results
        ])
        for r, stab in zip(results, stmt_tabs):
            with stab:
                a, s = r["account"], r["summary"]
                recon = r.get("_reconciliation") or {}
                anomalies = r.get("_anomalies", [])

                col_h, col_r = st.columns([2, 1])
                with col_h:
                    st.subheader(f"{a['bank']} -- account {a['account_last4']}")
                    st.caption(f"Period: {a['period']['start']} -> {a['period']['end']}")
                with col_r:
                    if recon.get("ok"):
                        st.markdown('<div class="reconciled-ok">RECONCILED</div>',
                                    unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="reconciled-bad">RECONCILIATION FAILED</div>',
                                    unsafe_allow_html=True)

                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("Beginning",  f"${s['beginning_balance']:,.2f}")
                c2.metric("Ending",     f"${s['ending_balance']:,.2f}")
                c3.metric("Deposits $", f"${s['deposits_total']:,.2f}")
                c4.metric("Deposits #", str(s.get("deposits_count")))
                c5.metric("Withdr. $",  f"${s['withdrawals_total']:,.2f}")
                c6.metric("Withdr. #",  str(s.get("withdrawals_count")))

                if not recon.get("ok") and recon.get("issues"):
                    st.warning("Reconciliation issues:")
                    for issue in recon["issues"]:
                        st.write(f"- {issue}")

                if anomalies:
                    st.markdown("**Anomalies**")
                    by_kind: dict = {}
                    for an in anomalies:
                        by_kind.setdefault(an["kind"], []).append(an)
                    chips = []
                    for kind, items in by_kind.items():
                        sev = items[0]["severity"]
                        chips.append(
                            f'<span class="badge-{sev}">{kind} x {len(items)}</span>'
                        )
                    st.markdown(" ".join(chips), unsafe_allow_html=True)
                    with st.expander(f"Show all {len(anomalies)} anomalies"):
                        st.dataframe(pd.DataFrame(anomalies), use_container_width=True)

                df = pd.DataFrame(r["transactions"])
                if df.empty:
                    st.info("No transactions.")
                    continue

                f1, f2, f3 = st.columns(3)
                with f1:
                    side_filter = st.radio(
                        "Side", ["all", "deposit", "withdrawal"],
                        horizontal=True,
                        key=f"side-{file_label}-{a['period']['start']}-{a['account_last4']}",
                    )
                with f2:
                    cat_filter = "all"
                    if "category" in df.columns:
                        cats = sorted({c for c in df["category"].dropna().unique()})
                        cat_filter = st.selectbox(
                            "Category", ["all"] + cats,
                            key=f"cat-{file_label}-{a['period']['start']}-{a['account_last4']}",
                        )
                with f3:
                    min_conf = 0.0
                    if "confidence" in df.columns and df["confidence"].notna().any():
                        min_conf = st.slider(
                            "Min confidence", 0.0, 1.0, 0.0, 0.05,
                            key=f"conf-{file_label}-{a['period']['start']}-{a['account_last4']}",
                        )

                view = df.copy()
                if side_filter == "deposit":
                    view = view[view["deposit"].notna()]
                elif side_filter == "withdrawal":
                    view = view[view["withdrawal"].notna()]
                if cat_filter != "all" and "category" in view.columns:
                    view = view[view["category"] == cat_filter]
                if min_conf > 0 and "confidence" in view.columns:
                    view = view[view["confidence"].fillna(0) >= min_conf]

                st.dataframe(view, use_container_width=True, height=360)

                d1, d2 = st.columns(2)
                with d1:
                    st.download_button(
                        ":arrow_down: JSON",
                        data=json.dumps(r, indent=2),
                        file_name=f"statement_{a['period']['start']}_{a['account_last4']}.json",
                        mime="application/json",
                        use_container_width=True,
                        key=f"dl-json-{file_label}-{a['period']['start']}",
                    )
                with d2:
                    csv_buf = io.StringIO()
                    df.to_csv(csv_buf, index=False)
                    st.download_button(
                        ":arrow_down: CSV",
                        data=csv_buf.getvalue(),
                        file_name=f"transactions_{a['period']['start']}_{a['account_last4']}.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key=f"dl-csv-{file_label}-{a['period']['start']}",
                    )
