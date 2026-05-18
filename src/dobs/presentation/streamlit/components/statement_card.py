from __future__ import annotations

import io
import json

import pandas as pd
import streamlit as st


def render_statement_card(stmt: dict, file_label: str) -> None:
    acct = stmt.get("account") or {}
    summ = stmt.get("summary") or {}
    recon = stmt.get("_reconciliation") or {}
    anomalies = stmt.get("_anomalies", [])
    period = acct.get("period") or {}

    col_h, col_r = st.columns([2, 1])
    with col_h:
        bank = acct.get("bank", "Unknown bank")
        last4 = acct.get("account_last4", "????")
        st.subheader(f"{bank} — account {last4}")
        st.caption(f"Period: {period.get('start', '?')} → {period.get('end', '?')}")
    with col_r:
        if recon.get("ok"):
            st.markdown('<div class="reconciled-ok">RECONCILED</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="reconciled-bad">RECONCILIATION FAILED</div>', unsafe_allow_html=True)

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
            chips.append(f'<span class="badge-{sev}">{kind} x {len(items)}</span>')
        st.markdown(" ".join(chips), unsafe_allow_html=True)
        with st.expander(f"Show all {len(anomalies)} anomalies"):
            st.dataframe(pd.DataFrame(anomalies), use_container_width=True)

    txns = stmt.get("transactions", [])
    df = pd.DataFrame(txns) if txns else pd.DataFrame()
    if df.empty:
        st.info("No transactions.")
        return

    period_key = period.get("start", "x")
    last4_key = acct.get("account_last4", "x")
    f1, f2, f3 = st.columns(3)
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
            data=json.dumps(stmt, indent=2),
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
