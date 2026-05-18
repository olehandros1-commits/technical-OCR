from __future__ import annotations

from typing import Any

import streamlit as st

from dobs.presentation.streamlit.client import ApiClient
from dobs.presentation.streamlit.components.statement_card import render_statement_card
from dobs.presentation.streamlit.state import SessionState


def _build_review_queue(results: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for s_idx, r in enumerate(results):
        acct = r.get("account") or {}
        period_start = (acct.get("period") or {}).get("start", "?")
        for t_idx, t in enumerate(r.get("transactions", [])):
            conf = t.get("confidence")
            if conf is not None and conf < threshold:
                queue.append(
                    {
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
                    }
                )
        for an in r.get("_anomalies", []):
            if an.get("severity") in ("warn", "error") and an.get("transaction_index") is not None:
                t_idx = an["transaction_index"]
                txns = r.get("transactions", [])
                if t_idx >= len(txns):
                    continue
                t = txns[t_idx]
                queue.append(
                    {
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
                    }
                )
    return queue


class ReviewPresenter:
    def __init__(self, client: ApiClient, state: SessionState) -> None:
        self._client = client
        self._state = state

    def render(self) -> None:
        results_by_file = self._state.results_by_file
        if not results_by_file:
            st.info(
                "Upload a PDF (or use the bundled sample) and click Run. "
                "The pipeline streams progress live."
            )
            st.stop()

        tel = self._state.telemetry
        if tel.get("total_calls", 0) or tel.get("total_cost_usd", 0):
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("LLM calls", tel.get("total_calls", 0))
            t2.metric("Input tokens", f"{tel.get('total_input_tokens', 0):,}")
            t3.metric("Output tokens", f"{tel.get('total_output_tokens', 0):,}")
            t4.metric("Cost (USD)", f"${tel.get('total_cost_usd', 0):.4f}")

        st.markdown("---")

        thr = self._state.review_threshold
        file_tabs = st.tabs(list(results_by_file.keys()))

        for file_label, file_tab in zip(results_by_file.keys(), file_tabs):
            results = results_by_file[file_label]
            with file_tab:
                if not results:
                    st.warning(f"No statements extracted from **{file_label}**.")
                    continue

                self._render_file_tab(file_label, results, thr)

    def _render_file_tab(self, file_label: str, results: list[dict[str, Any]], thr: float) -> None:
        total_tx = sum(len(r.get("transactions", [])) for r in results)
        ok_count = sum(1 for r in results if (r.get("_reconciliation") or {}).get("ok"))
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
                self._render_review_queue(file_label, results, review_queue)

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
                render_statement_card(r, file_label)

        st.markdown("---")
        if st.button(
            f":arrow_down: Download all statements as Excel ({file_label})",
            key=f"xlsx-btn-{file_label}",
            use_container_width=True,
        ):
            self._download_xlsx(file_label)

    def _render_review_queue(
        self, file_label: str, results: list[dict[str, Any]], queue: list[dict[str, Any]]
    ) -> None:
        for i, item in enumerate(queue[:30]):
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
                self._client.post_review(item["statement_key"], item["tx_idx"], "approve")
                st.success("Approved.")
            if cols[3].button("Reject", key=f"reject-{file_label}-{i}"):
                self._client.post_review(item["statement_key"], item["tx_idx"], "reject")
                st.warning("Rejected.")
            if item.get("anomaly") and cols[4].button("Explain", key=f"explain-{file_label}-{i}"):
                txns = results[item["stmt_idx"]].get("transactions", [])
                tx = txns[item["tx_idx"]] if item["tx_idx"] < len(txns) else None
                explanation = self._client.explain_anomaly(item["anomaly"], tx)
                st.info(explanation)
        if len(queue) > 30:
            st.caption(f"…and {len(queue) - 30} more")

    def _download_xlsx(self, file_label: str) -> None:
        results_by_file = self._state.results_by_file
        results = results_by_file.get(file_label, [])
        if not results:
            st.error("No results to export.")
            return

        pdf_bytes: bytes | None = None
        pdf_name = file_label
        if st.session_state.get("_inputs"):
            for pb, pn, _, _ in st.session_state["_inputs"]:
                if pn == file_label:
                    pdf_bytes = pb
                    pdf_name = pn
                    break

        if pdf_bytes is None:
            st.error("Original PDF not available for Excel export. Re-run extraction first.")
            return

        try:
            with st.spinner("Generating Excel…"):
                xlsx_bytes = self._client.export_xlsx(
                    pdf_bytes,
                    pdf_name,
                    self._state.tier,
                    self._state.enrich,
                    self._state.parallel,
                )
            st.download_button(
                ":arrow_down: Save Excel",
                data=xlsx_bytes,
                file_name=f"{pdf_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"dl-xlsx-{file_label}",
            )
        except Exception as exc:
            st.error(f"Excel export failed: {exc}")
