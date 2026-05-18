"""Streamlit UI for dobs.ai — talks to the local /api/v1/* HTTP API."""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import pandas as pd  # noqa: E402
import requests  # noqa: E402
import streamlit as st  # noqa: E402

API_BASE = os.getenv("DOBS_API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="dobs.ai — Statement Extractor",
    page_icon=":bank:",
    layout="wide",
)

st.markdown(
    """
    <style>
    .reconciled-ok  { color:#16a34a; font-weight:600; }
    .reconciled-bad { color:#dc2626; font-weight:600; }
    .badge-info  { background:#dbeafe; color:#1e40af; padding:2px 8px;
                   border-radius:8px; font-size:11px; margin-right:4px; }
    .badge-warn  { background:#fef3c7; color:#92400e; padding:2px 8px;
                   border-radius:8px; font-size:11px; margin-right:4px; }
    .badge-error { background:#fee2e2; color:#991b1b; padding:2px 8px;
                   border-radius:8px; font-size:11px; margin-right:4px; }
    .review-row  { background:#fafafa; border-left:3px solid #f59e0b;
                   padding:6px 10px; margin:4px 0; border-radius:4px; }
    div[data-testid="stMetricLabel"] { font-size:12px; color:#6b7280; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _api_headers() -> dict[str, str]:
    key = os.getenv("EXTRACTOR_API_KEYS", "")
    first = next((k.strip() for k in key.split(",") if k.strip()), "")
    return {"x-api-key": first} if first else {}


def _get_tiers() -> list[str]:
    try:
        r = requests.get(f"{API_BASE}/api/v1/telemetry/tiers",
                         headers=_api_headers(), timeout=4)
        r.raise_for_status()
        return [t.get("name", t.get("id", "")) for t in r.json().get("tiers", [])]
    except Exception:
        return []


st.sidebar.title(":bank: dobs.ai")
st.sidebar.markdown("**Bank Statement Extractor**")

tiers = _get_tiers()
tier_options = ["(default)"] + tiers
tier_choice = st.sidebar.selectbox("Tier", tier_options, index=0)

enrich = st.sidebar.toggle("Enrich (category + confidence)", value=True)
review_threshold = st.sidebar.slider(
    "Review threshold (confidence below = needs human)", 0.0, 1.0, 0.5, 0.05
)
parallel = st.sidebar.slider("Parallel statements", 1, 6, 2)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Pipeline: ingest → segment → summary → transactions → "
    "reconcile → repair → enrich → anomaly → HITL."
)

st.title("Bank Statement Extractor")
st.caption(
    "Drop one or several bank-statement PDFs. "
    "The pipeline streams progress live and returns reconciled structured JSON."
)

col_pdf, col_txt = st.columns([2, 1])
with col_pdf:
    uploaded_pdfs = st.file_uploader(
        "Statement PDF(s)", type=["pdf"], accept_multiple_files=True
    )
with col_txt:
    uploaded_txts = st.file_uploader(
        "Pre-OCR'd text file(s) (optional)",
        type=["txt"],
        accept_multiple_files=True,
        help="Match by filename stem (e.g. chase_apr.txt → chase_apr.pdf).",
    )

use_sample = st.button(
    ":file_folder: Use bundled Ixonia sample", use_container_width=True
)


def _build_inputs() -> list[tuple[bytes, str, bytes | None, str]]:
    if use_sample:
        sample_pdf = ROOT / "Binder2_Redacted.pdf"
        sample_txt = ROOT / "ixonia_ocr.txt"
        if not sample_pdf.exists():
            st.error(f"Sample PDF not found: {sample_pdf}")
            return []
        txt_bytes = sample_txt.read_bytes() if sample_txt.exists() else None
        return [(sample_pdf.read_bytes(), "Ixonia (bundled)", txt_bytes, "ixonia_ocr.txt")]
    if not uploaded_pdfs:
        return []
    txt_by_stem: dict[str, tuple[bytes, str]] = {}
    for f in (uploaded_txts or []):
        txt_by_stem[Path(f.name).stem] = (f.getvalue(), f.name)
    results: list[tuple[bytes, str, bytes | None, str]] = []
    for f in uploaded_pdfs:
        stem = Path(f.name).stem
        txt_pair = txt_by_stem.get(stem)
        results.append((
            f.getvalue(), f.name,
            txt_pair[0] if txt_pair else None,
            txt_pair[1] if txt_pair else "",
        ))
    return results


def _stream_extract(
    pdf_bytes: bytes,
    pdf_name: str,
    txt_bytes: bytes | None,
    txt_name: str,
    log_placeholder,
    log_lines: list[str],
) -> list[dict]:
    tier = "" if tier_choice == "(default)" else tier_choice

    job_resp = requests.post(
        f"{API_BASE}/api/v1/extraction/jobs",
        headers=_api_headers(),
        files={"pdf": (pdf_name, io.BytesIO(pdf_bytes), "application/pdf")},
        data={
            "tier": tier,
            "enrich": str(enrich).lower(),
            "parallel": str(parallel),
        },
        timeout=30,
    )
    job_resp.raise_for_status()
    job_id = job_resp.json()["job_id"]

    log_lines.append(f"`queued` job **{job_id[:8]}…**")
    log_placeholder.markdown("\n\n".join(log_lines[-60:]))

    t0 = time.time()
    try:
        with requests.get(
            f"{API_BASE}/api/v1/extraction/jobs/{job_id}/events",
            headers=_api_headers(),
            stream=True,
            timeout=300,
        ) as sse:
            for raw in sse.iter_lines():
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
                log_placeholder.markdown("\n\n".join(log_lines[-60:]))
                if evt == "done":
                    break
    except requests.exceptions.Timeout:
        log_lines.append("`timeout` SSE stream timed out — polling for result")
        log_placeholder.markdown("\n\n".join(log_lines[-60:]))

    for _ in range(60):
        poll = requests.get(
            f"{API_BASE}/api/v1/extraction/jobs/{job_id}",
            headers=_api_headers(),
            timeout=10,
        )
        poll.raise_for_status()
        body = poll.json()
        if body.get("done"):
            if body.get("error"):
                raise RuntimeError(body["error"])
            return body.get("results") or []
        time.sleep(2)

    raise TimeoutError(f"Job {job_id} did not complete within 120 s")


inputs = _build_inputs()
go = st.button(
    f":arrow_forward: Run extraction on {len(inputs)} file(s)"
    if inputs
    else ":arrow_forward: Run extraction (upload a PDF first)",
    type="primary",
    disabled=not inputs,
    use_container_width=True,
)

if go and inputs:
    progress_container = st.container()
    progress_log = progress_container.empty()
    log_lines: list[str] = []
    all_results_by_file: dict[str, list[dict]] = {}
    telemetry_by_file: dict[str, dict] = {}

    for pdf_bytes, pdf_name, txt_bytes, txt_name in inputs:
        log_lines.append(f"\n### Processing **{pdf_name}**")
        progress_log.markdown("\n\n".join(log_lines[-60:]))
        try:
            with st.spinner(f"{pdf_name}: running pipeline…"):
                results = _stream_extract(
                    pdf_bytes, pdf_name, txt_bytes, txt_name,
                    progress_log, log_lines,
                )
        except Exception as exc:
            st.error(f"{pdf_name}: {exc}")
            results = []
        all_results_by_file[pdf_name] = results

    try:
        tel_resp = requests.get(
            f"{API_BASE}/api/v1/telemetry",
            headers=_api_headers(),
            timeout=5,
        )
        tel_resp.raise_for_status()
        st.session_state["telemetry"] = tel_resp.json()
    except Exception:
        st.session_state["telemetry"] = {}

    st.session_state["results_by_file"] = all_results_by_file
    st.session_state["review_threshold"] = review_threshold

results_by_file: dict[str, list[dict]] = st.session_state.get("results_by_file", {})
if not results_by_file:
    st.info(
        "Upload a PDF (or use the bundled sample) and click Run. "
        "The pipeline streams progress live."
    )
    st.stop()

tel: dict = st.session_state.get("telemetry", {})
if tel.get("total_calls", 0) or tel.get("total_cost_usd", 0):
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("LLM calls", tel.get("total_calls", 0))
    t2.metric("Input tokens", f"{tel.get('total_input_tokens', 0):,}")
    t3.metric("Output tokens", f"{tel.get('total_output_tokens', 0):,}")
    t4.metric("Cost (USD)", f"${tel.get('total_cost_usd', 0):.4f}")

st.markdown("---")


def _build_review_queue(results: list[dict], threshold: float) -> list[dict]:
    queue: list[dict] = []
    for s_idx, r in enumerate(results):
        acct = r.get("account") or {}
        period_start = (acct.get("period") or {}).get("start", "?")
        for t_idx, t in enumerate(r.get("transactions", [])):
            conf = t.get("confidence")
            if conf is not None and conf < threshold:
                queue.append({
                    "stmt_idx": s_idx,
                    "tx_idx": t_idx,
                    "period": period_start,
                    "date": t.get("date", ""),
                    "description": t.get("description", ""),
                    "amount": t.get("deposit") or t.get("withdrawal") or 0,
                    "side": "deposit" if t.get("deposit") else "withdrawal",
                    "confidence": conf,
                    "reason": f"low confidence ({conf:.2f})",
                    "anomaly": None,
                    "statement_key": f"{period_start}_{acct.get('account_last4', '')}",
                })
        for an in r.get("_anomalies", []):
            if an.get("severity") in ("warn", "error") and an.get("transaction_index") is not None:
                t_idx = an["transaction_index"]
                txns = r.get("transactions", [])
                if t_idx >= len(txns):
                    continue
                t = txns[t_idx]
                queue.append({
                    "stmt_idx": s_idx,
                    "tx_idx": t_idx,
                    "period": period_start,
                    "date": t.get("date", ""),
                    "description": t.get("description", ""),
                    "amount": t.get("deposit") or t.get("withdrawal") or 0,
                    "side": "deposit" if t.get("deposit") else "withdrawal",
                    "confidence": t.get("confidence"),
                    "reason": f"{an['kind']}: {an['message']}",
                    "anomaly": an,
                    "statement_key": f"{period_start}_{acct.get('account_last4', '')}",
                })
    return queue


def _post_review(stmt_key: str, tx_idx: int, decision: str) -> None:
    try:
        requests.post(
            f"{API_BASE}/api/v1/reviews",
            headers={**_api_headers(), "Content-Type": "application/json"},
            json={"statement_key": stmt_key, "tx_index": tx_idx, "decision": decision},
            timeout=5,
        )
    except Exception:
        pass


def _explain_anomaly(anomaly: dict, transaction: dict | None) -> str:
    try:
        r = requests.post(
            f"{API_BASE}/api/v1/reviews/explain",
            headers={**_api_headers(), "Content-Type": "application/json"},
            json={"anomaly": anomaly, "transaction": transaction},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("explanation", r.text)
    except Exception as exc:
        return f"Could not fetch explanation: {exc}"


file_tabs = st.tabs(list(results_by_file.keys()))
thr = st.session_state.get("review_threshold", review_threshold)

for file_label, file_tab in zip(results_by_file.keys(), file_tabs):
    results = results_by_file[file_label]
    with file_tab:
        if not results:
            st.warning(f"No statements extracted from **{file_label}**.")
            continue

        total_tx = sum(len(r.get("transactions", [])) for r in results)
        ok_count = sum(
            1 for r in results if (r.get("_reconciliation") or {}).get("ok")
        )
        total_anom = sum(len(r.get("_anomalies", [])) for r in results)
        review_queue = _build_review_queue(results, thr)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Statements", len(results))
        m2.metric("Reconciled", f"{ok_count}/{len(results)}")
        m3.metric("Transactions", total_tx)
        m4.metric("Need review", len(review_queue))

        if review_queue:
            with st.expander(
                f":raising_hand: Human review queue ({len(review_queue)} items)",
                expanded=True,
            ):
                for i, item in enumerate(review_queue[:30]):
                    cols = st.columns([3, 1, 1, 1, 1])
                    cols[0].markdown(
                        f"<div class='review-row'><b>{item['date']}</b> · "
                        f"{item['description'][:80]}<br>"
                        f"<small>{item['reason']}</small></div>",
                        unsafe_allow_html=True,
                    )
                    amount = item["amount"]
                    try:
                        cols[1].write(f"${float(amount):,.2f} {item['side'][0].upper()}")
                    except (TypeError, ValueError):
                        cols[1].write(str(amount))
                    if cols[2].button("Approve", key=f"approve-{file_label}-{i}"):
                        _post_review(item["statement_key"], item["tx_idx"], "approve")
                        st.success("Approved.")
                    if cols[3].button("Reject", key=f"reject-{file_label}-{i}"):
                        _post_review(item["statement_key"], item["tx_idx"], "reject")
                        st.warning("Rejected.")
                    if item.get("anomaly") and cols[4].button(
                        "Explain", key=f"explain-{file_label}-{i}"
                    ):
                        txns = results[item["stmt_idx"]].get("transactions", [])
                        tx = txns[item["tx_idx"]] if item["tx_idx"] < len(txns) else None
                        explanation = _explain_anomaly(item["anomaly"], tx)
                        st.info(explanation)
                if len(review_queue) > 30:
                    st.caption(f"…and {len(review_queue) - 30} more")

        st.markdown("### Statements")
        stmt_tab_labels = []
        for r in results:
            acct = r.get("account") or {}
            period = (acct.get("period") or {}).get("start", "?")
            last4 = acct.get("account_last4", "????")
            stmt_tab_labels.append(f"{period}  ({last4})")

        stmt_tabs = st.tabs(stmt_tab_labels)
        for r, stab in zip(results, stmt_tabs):
            with stab:
                acct = r.get("account") or {}
                summ = r.get("summary") or {}
                recon = r.get("_reconciliation") or {}
                anomalies = r.get("_anomalies", [])

                col_h, col_r = st.columns([2, 1])
                with col_h:
                    bank = acct.get("bank", "Unknown bank")
                    last4 = acct.get("account_last4", "????")
                    st.subheader(f"{bank} — account {last4}")
                    period = acct.get("period") or {}
                    st.caption(
                        f"Period: {period.get('start', '?')} → {period.get('end', '?')}"
                    )
                with col_r:
                    if recon.get("ok"):
                        st.markdown(
                            '<div class="reconciled-ok">RECONCILED</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<div class="reconciled-bad">RECONCILIATION FAILED</div>',
                            unsafe_allow_html=True,
                        )

                c1, c2, c3, c4, c5, c6 = st.columns(6)
                beg = summ.get("beginning_balance", 0)
                end = summ.get("ending_balance", 0)
                dep = summ.get("deposits_total", 0)
                dep_n = summ.get("deposits_count", "—")
                wdr = summ.get("withdrawals_total", 0)
                wdr_n = summ.get("withdrawals_count", "—")
                c1.metric("Beginning", f"${beg:,.2f}")
                c2.metric("Ending", f"${end:,.2f}")
                c3.metric("Deposits $", f"${dep:,.2f}")
                c4.metric("Deposits #", str(dep_n))
                c5.metric("Withdr. $", f"${wdr:,.2f}")
                c6.metric("Withdr. #", str(wdr_n))

                if not recon.get("ok") and recon.get("issues"):
                    st.warning("Reconciliation issues:")
                    for issue in recon["issues"]:
                        st.write(f"- {issue}")

                if anomalies:
                    st.markdown("**Anomalies**")
                    by_kind: dict[str, list] = {}
                    for an in anomalies:
                        by_kind.setdefault(an.get("kind", "unknown"), []).append(an)
                    chips = []
                    for kind, items in by_kind.items():
                        sev = items[0].get("severity", "info")
                        chips.append(
                            f'<span class="badge-{sev}">{kind} x {len(items)}</span>'
                        )
                    st.markdown(" ".join(chips), unsafe_allow_html=True)
                    with st.expander(f"Show all {len(anomalies)} anomalies"):
                        st.dataframe(pd.DataFrame(anomalies), use_container_width=True)

                txns = r.get("transactions", [])
                df = pd.DataFrame(txns) if txns else pd.DataFrame()
                if df.empty:
                    st.info("No transactions.")
                    continue

                f1, f2, f3 = st.columns(3)
                period_key = period.get("start", "x")
                last4_key = acct.get("account_last4", "x")
                with f1:
                    side_filter = st.radio(
                        "Side",
                        ["all", "deposit", "withdrawal"],
                        horizontal=True,
                        key=f"side-{file_label}-{period_key}-{last4_key}",
                    )
                with f2:
                    cat_filter = "all"
                    if "category" in df.columns:
                        cats = sorted({c for c in df["category"].dropna().unique()})
                        cat_filter = st.selectbox(
                            "Category",
                            ["all"] + cats,
                            key=f"cat-{file_label}-{period_key}-{last4_key}",
                        )
                with f3:
                    min_conf = 0.0
                    if "confidence" in df.columns and df["confidence"].notna().any():
                        min_conf = st.slider(
                            "Min confidence",
                            0.0, 1.0, 0.0, 0.05,
                            key=f"conf-{file_label}-{period_key}-{last4_key}",
                        )

                view = df.copy()
                if side_filter == "deposit":
                    view = view[view["deposit"].notna()] if "deposit" in view.columns else view
                elif side_filter == "withdrawal":
                    view = view[view["withdrawal"].notna()] if "withdrawal" in view.columns else view
                if cat_filter != "all" and "category" in view.columns:
                    view = view[view["category"] == cat_filter]
                if min_conf > 0 and "confidence" in view.columns:
                    view = view[view["confidence"].fillna(0) >= min_conf]

                st.dataframe(view, use_container_width=True, height=360)

                period_start = period.get("start", "unknown")
                d1, d2 = st.columns(2)
                with d1:
                    st.download_button(
                        ":arrow_down: JSON",
                        data=json.dumps(r, indent=2),
                        file_name=f"statement_{period_start}_{last4_key}.json",
                        mime="application/json",
                        use_container_width=True,
                        key=f"dl-json-{file_label}-{period_start}-{last4_key}",
                    )
                with d2:
                    csv_buf = io.StringIO()
                    df.to_csv(csv_buf, index=False)
                    st.download_button(
                        ":arrow_down: CSV",
                        data=csv_buf.getvalue(),
                        file_name=f"transactions_{period_start}_{last4_key}.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key=f"dl-csv-{file_label}-{period_start}-{last4_key}",
                    )

        st.markdown("---")
        xlsx_label = f":arrow_down: Download all statements as Excel ({file_label})"
        if st.button(xlsx_label, key=f"xlsx-btn-{file_label}", use_container_width=True):
            pdf_bytes_for_xlsx: bytes | None = None
            pdf_name_for_xlsx = file_label
            for pb, pn, _, _ in inputs:
                if pn == file_label:
                    pdf_bytes_for_xlsx = pb
                    break
            if pdf_bytes_for_xlsx is None and inputs:
                pdf_bytes_for_xlsx = inputs[0][0]
                pdf_name_for_xlsx = inputs[0][1]

            if pdf_bytes_for_xlsx:
                tier = "" if tier_choice == "(default)" else tier_choice
                try:
                    with st.spinner("Generating Excel…"):
                        xlsx_resp = requests.post(
                            f"{API_BASE}/api/v1/extraction/export/xlsx",
                            headers=_api_headers(),
                            files={
                                "pdf": (
                                    pdf_name_for_xlsx,
                                    io.BytesIO(pdf_bytes_for_xlsx),
                                    "application/pdf",
                                )
                            },
                            data={
                                "tier": tier,
                                "enrich": str(enrich).lower(),
                                "parallel": str(parallel),
                            },
                            timeout=120,
                        )
                        xlsx_resp.raise_for_status()
                    st.download_button(
                        ":arrow_down: Save Excel",
                        data=xlsx_resp.content,
                        file_name=f"{pdf_name_for_xlsx}.xlsx",
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                        use_container_width=True,
                        key=f"dl-xlsx-{file_label}",
                    )
                except Exception as exc:
                    st.error(f"Excel export failed: {exc}")


def run() -> None:
    import subprocess  # noqa: PLC0415
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", __file__,
         "--server.headless", "true"],
        close_fds=True,
    )


def main() -> None:
    pass
