import type { RecurringGroup } from "../model/types";

interface Props {
  groups: RecurringGroup[];
}

/** Compact panel listing recurring transaction groups (subscriptions,
 *  payroll, rent) detected by the deterministic recurring stage. */
export function RecurringPanel({ groups }: Props) {
  if (!groups || groups.length === 0) return null;

  return (
    <div className="recurring-panel">
      <h4>Recurring &amp; subscriptions <span className="muted">({groups.length})</span></h4>
      <table className="recurring-table">
        <thead>
          <tr>
            <th>Vendor / key</th>
            <th>Side</th>
            <th className="num">Avg</th>
            <th>Cadence</th>
            <th className="num">Count</th>
            <th>Next predicted</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g, i) => (
            <tr key={i}>
              <td>{g.vendor_key}</td>
              <td>
                <span className={`recur-side ${g.side}`}>{g.side[0].toUpperCase()}</span>
              </td>
              <td className="num">${g.avg_amount.toLocaleString()}</td>
              <td>
                <span className={`cadence-pill cadence-${g.cadence_label}`}>
                  {g.cadence_label}
                </span>
                <span className="muted small">({g.cadence_days.toFixed(0)}d)</span>
              </td>
              <td className="num">{g.count}</td>
              <td className="muted">{g.next_predicted_date ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
