import { useMemo, useState } from "react";
import { diffExtractions, type ExtractionDiff } from "../api";
import type { StatementResult } from "../types";

interface Props {
  results: StatementResult[];
}

/** QA panel: pick two extractions of the same statement and view a
 *  structured diff (added / removed / changed rows + summary deltas).
 *
 *  When only one extraction is loaded for a given (period, account)
 *  pair, the user can paste a prior JSON to compare against; otherwise
 *  we offer two cached statements with matching account/period as A/B.
 */
export function DiffView({ results }: Props) {
  const [aIdx, setAIdx] = useState<number>(0);
  const [bIdx, setBIdx] = useState<number>(0);
  const [diff, setDiff] = useState<ExtractionDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const labels = useMemo(
    () => results.map((r, i) =>
      `${i + 1}. ${r.account.period.start} → ${r.account.period.end}` +
      ` · acct ${r.account.account_last4 ?? "?"}`),
    [results],
  );

  const run = async () => {
    setBusy(true); setError(null); setDiff(null);
    try {
      const d = await diffExtractions(results[aIdx], results[bIdx]);
      setDiff(d);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (results.length < 2) return null;

  return (
    <section className="diff-view">
      <h3>Diff view  <span className="muted small">A/B compare two extractions</span></h3>
      <div className="diff-controls">
        <label>
          <span>A (baseline)</span>
          <select value={aIdx} onChange={(e) => setAIdx(Number(e.target.value))}>
            {labels.map((l, i) => <option key={i} value={i}>{l}</option>)}
          </select>
        </label>
        <label>
          <span>B (compare)</span>
          <select value={bIdx} onChange={(e) => setBIdx(Number(e.target.value))}>
            {labels.map((l, i) => <option key={i} value={i}>{l}</option>)}
          </select>
        </label>
        <button onClick={run} disabled={busy || aIdx === bIdx} className="diff-go">
          {busy ? "…" : "Compute diff"}
        </button>
        {aIdx === bIdx && <span className="muted small">pick distinct A and B</span>}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {diff && (
        <div className="diff-result">
          <div className="diff-metrics">
            <div className="diff-metric ok">
              <span>Common rows</span><strong>{diff.common_count}</strong>
            </div>
            <div className="diff-metric added">
              <span>Only in B (added)</span><strong>+{diff.only_in_b_count}</strong>
            </div>
            <div className="diff-metric removed">
              <span>Only in A (removed)</span><strong>−{diff.only_in_a_count}</strong>
            </div>
            <div className="diff-metric changed">
              <span>Changed fields</span><strong>{diff.changed_count}</strong>
            </div>
          </div>

          {Object.keys(diff.summary_deltas).length > 0 && (
            <div className="diff-section">
              <h4>Summary deltas</h4>
              <table className="diff-table">
                <thead><tr><th>Field</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
                <tbody>
                  {Object.entries(diff.summary_deltas).map(([f, v]) => (
                    <tr key={f}>
                      <td>{f}</td>
                      <td>{String(v.a)}</td>
                      <td>{String(v.b)}</td>
                      <td className={(v.delta ?? 0) >= 0 ? "ok" : "bad"}>
                        {v.delta != null ? (v.delta >= 0 ? "+" : "") + v.delta : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {diff.only_in_b.length > 0 && (
            <div className="diff-section">
              <h4 className="ok">Added in B (first {diff.only_in_b.length})</h4>
              <DiffRowList rows={diff.only_in_b} />
            </div>
          )}
          {diff.only_in_a.length > 0 && (
            <div className="diff-section">
              <h4 className="bad">Removed (only in A, first {diff.only_in_a.length})</h4>
              <DiffRowList rows={diff.only_in_a} />
            </div>
          )}
          {diff.changed.length > 0 && (
            <div className="diff-section">
              <h4>Changed soft fields</h4>
              <ul className="diff-changed">
                {diff.changed.slice(0, 20).map((c, i) => (
                  <li key={i}>
                    <code>{(c.key as unknown as string[]).join(" | ")}</code>:&nbsp;
                    {Object.entries(c.fields).map(([f, ab]) => (
                      <span key={f} className="diff-field-change">
                        <em>{f}</em>: <s>{String(ab.a)}</s> → <strong>{String(ab.b)}</strong>
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function DiffRowList({ rows }: { rows: any[] }) {
  return (
    <table className="diff-table">
      <thead><tr><th>Date</th><th>Description</th><th className="num">Deposit</th><th className="num">Withdrawal</th></tr></thead>
      <tbody>
        {rows.slice(0, 20).map((r, i) => (
          <tr key={i}>
            <td>{r.date}</td>
            <td className="desc">{r.description}</td>
            <td className="num">{r.deposit != null ? `$${r.deposit}` : ""}</td>
            <td className="num">{r.withdrawal != null ? `$${r.withdrawal}` : ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
