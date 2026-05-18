import { useMemo, useState } from "react";
import type { StatementResult, TxCategory, Anomaly } from "../types";
import { TransactionsTable } from "./TransactionsTable";
import { RecurringPanel } from "./RecurringPanel";
import { ReconciliationChart } from "./ReconciliationChart";
import { explainAnomaly, type ExplainResult } from "../api";

interface Props {
  statement: StatementResult;
}

export function StatementCard({ statement }: Props) {
  const { account, summary, _reconciliation, _anomalies, transactions } = statement;
  const [showAnomalies, setShowAnomalies] = useState(false);
  const [explanations, setExplanations] = useState<Record<number, ExplainResult | "loading" | "error">>({});

  const askExplain = async (idx: number, an: Anomaly) => {
    setExplanations((s) => ({ ...s, [idx]: "loading" }));
    try {
      const tx = an.transaction_index != null ? transactions[an.transaction_index] : null;
      const ctx = transactions.slice(
        Math.max(0, (an.transaction_index ?? 0) - 3),
        (an.transaction_index ?? 0) + 4,
      );
      const r = await explainAnomaly(an, tx, ctx);
      setExplanations((s) => ({ ...s, [idx]: r }));
    } catch (e) {
      console.error(e);
      setExplanations((s) => ({ ...s, [idx]: "error" }));
    }
  };

  const ok = _reconciliation?.ok ?? false;

  const anomaliesByKind = useMemo(() => {
    const out: Record<string, number> = {};
    for (const a of _anomalies) out[a.kind] = (out[a.kind] ?? 0) + 1;
    return out;
  }, [_anomalies]);

  const categoryTotals = useMemo(() => {
    const out: Record<TxCategory, { count: number; amount: number }> = {} as never;
    for (const t of transactions) {
      const c = t.category ?? "OTHER";
      if (!out[c]) out[c] = { count: 0, amount: 0 };
      out[c].count += 1;
      out[c].amount += (t.deposit ?? t.withdrawal ?? 0);
    }
    return out;
  }, [transactions]);

  return (
    <article className="statement-card">
      <header className="card-header">
        <div>
          <h3>
            {account.bank}{" "}
            <span className="muted">- account {account.account_last4}</span>
          </h3>
          <span className="period">
            {account.period.start} {"->"} {account.period.end}
            {summary.currency && <span className="currency"> · {summary.currency}</span>}
          </span>
        </div>
        <span className={`status-pill ${ok ? "ok" : "bad"}`}>
          {ok ? "RECONCILED" : "MISMATCH"}
        </span>
      </header>

      <div className="metric-grid">
        <Metric label="Beginning" value={fmtUsd(summary.beginning_balance)} />
        <Metric label="Ending" value={fmtUsd(summary.ending_balance)} />
        <Metric label="Deposits" value={fmtUsd(summary.deposits_total)}
                sub={`# ${summary.deposits_count ?? "?"}`} />
        <Metric label="Withdrawals" value={fmtUsd(summary.withdrawals_total)}
                sub={`# ${summary.withdrawals_count ?? "?"}`} />
      </div>

      {!ok && _reconciliation?.issues.length ? (
        <div className="issues">
          <strong>Reconciliation issues:</strong>
          <ul>
            {_reconciliation.issues.map((i, idx) => <li key={idx}>{i}</li>)}
          </ul>
        </div>
      ) : null}

      {_anomalies.length > 0 && (
        <div className="anomalies">
          <div className="anomaly-chips">
            {Object.entries(anomaliesByKind).map(([kind, n]) => {
              const sev = _anomalies.find((a) => a.kind === kind)?.severity ?? "info";
              return (
                <span key={kind} className={`chip sev-${sev}`}>
                  {kind} x {n}
                </span>
              );
            })}
            <button
              className="anomaly-toggle"
              onClick={() => setShowAnomalies((v) => !v)}
            >
              {showAnomalies ? "Hide details" : "Show details"}
            </button>
          </div>
          {showAnomalies && (
            <table className="anomaly-table">
              <thead>
                <tr>
                  <th>Kind</th><th>Severity</th><th>Tx idx</th>
                  <th>Message</th><th>Explain</th>
                </tr>
              </thead>
              <tbody>
                {_anomalies.map((a, i) => {
                  const exp = explanations[i];
                  return (
                    <tr key={i}>
                      <td>{a.kind}</td>
                      <td className={`sev sev-${a.severity}`}>{a.severity}</td>
                      <td>{a.transaction_index ?? "-"}</td>
                      <td>
                        {a.message}
                        {exp && typeof exp === "object" && (
                          <div className="explain-bubble">
                            <strong>Explanation:</strong> {exp.summary}
                            <br />
                            <em>Suggested action:</em> {exp.suggested_action}
                          </div>
                        )}
                        {exp === "error" && (
                          <div className="explain-bubble error">
                            Couldn’t generate explanation — see API logs.
                          </div>
                        )}
                      </td>
                      <td>
                        <button
                          className="explain-btn"
                          disabled={exp === "loading"}
                          onClick={() => askExplain(i, a)}
                        >
                          {exp === "loading" ? "…" : exp ? "Re-ask" : "Explain"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {Object.keys(categoryTotals).length > 0 && (
        <div className="cat-strip">
          {Object.entries(categoryTotals)
            .sort((a, b) => b[1].amount - a[1].amount)
            .slice(0, 8)
            .map(([cat, data]) => (
              <div key={cat} className="cat-pill">
                <span className="cat-name">{cat}</span>
                <span className="cat-meta">
                  {data.count} · {fmtUsd(data.amount)}
                </span>
              </div>
            ))}
        </div>
      )}

      <ReconciliationChart statement={statement} />

      <RecurringPanel groups={statement._recurring ?? []} />

      <TransactionsTable transactions={transactions} />

      <div className="downloads">
        <button onClick={() => downloadJson(statement)}>
          Download JSON
        </button>
        <button onClick={() => downloadCsv(statement)}>
          Download CSV
        </button>
      </div>
    </article>
  );
}

function Metric(
  { label, value, sub }: { label: string; value: string; sub?: string },
) {
  return (
    <div className="m">
      <span className="m-label">{label}</span>
      <span className="m-value">{value}</span>
      {sub && <span className="m-sub">{sub}</span>}
    </div>
  );
}

function fmtUsd(n: number): string {
  return n.toLocaleString(undefined, {
    style: "currency", currency: "USD",
  });
}

function downloadJson(s: StatementResult) {
  const blob = new Blob([JSON.stringify(s, null, 2)], { type: "application/json" });
  triggerDownload(blob, `statement_${s.account.period.start}_${s.account.account_last4}.json`);
}

function downloadCsv(s: StatementResult) {
  const cols = ["date", "description", "deposit", "withdrawal", "category", "vendor", "confidence"];
  const lines = [cols.join(",")];
  for (const t of s.transactions) {
    lines.push(cols.map((c) => csvCell((t as never)[c])).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  triggerDownload(blob, `transactions_${s.account.period.start}_${s.account.account_last4}.csv`);
}

function csvCell(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n"))
    return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function triggerDownload(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}
