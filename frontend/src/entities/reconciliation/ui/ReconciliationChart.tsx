import { useMemo } from "react";
import type { Anomaly } from "@/entities/anomaly";
import type { StatementResult } from "@/entities/statement";
import type { Transaction } from "@/entities/transaction";

interface Props {
  statement: StatementResult;
}

/** Running-balance day-by-day chart with anomaly markers.
 *
 *  Pure inline SVG -- zero chart dependency. Good enough for the UI's
 *  "look at the financial trajectory" panel; for production-grade
 *  interaction you'd swap in Recharts/d3 later.
 */
export function ReconciliationChart({ statement }: Props) {
  const data = useMemo(() => buildSeries(statement), [statement]);
  if (data.points.length < 2) {
    return null;
  }

  const W = 720;
  const H = 200;
  const PAD_L = 56;
  const PAD_R = 12;
  const PAD_T = 16;
  const PAD_B = 28;

  const xs = data.points.map((_, i) => i);
  const xScale = (i: number) =>
    PAD_L + (i / (xs.length - 1 || 1)) * (W - PAD_L - PAD_R);
  const yScale = (v: number) => {
    const range = data.max - data.min || 1;
    return PAD_T + (1 - (v - data.min) / range) * (H - PAD_T - PAD_B);
  };

  const linePath = data.points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xScale(i)},${yScale(p.balance)}`)
    .join(" ");

  const fillPath =
    `${linePath} L${xScale(data.points.length - 1)},${H - PAD_B} ` +
    `L${xScale(0)},${H - PAD_B} Z`;

  // Y-axis ticks: min, midpoint, max.
  const yTicks = [data.min, (data.min + data.max) / 2, data.max];
  // X-axis: ~5 evenly-spaced date labels.
  const xTickIdxs = Array.from({ length: Math.min(5, data.points.length) }, (_, k) =>
    Math.round((k / Math.max(1, 4)) * (data.points.length - 1)),
  );

  return (
    <div className="recon-chart">
      <div className="recon-chart-header">
        <h4>Running balance</h4>
        <span className="recon-chart-legend">
          <span className="dot ok" /> daily balance &nbsp;
          <span className="dot warn" /> warn anomaly &nbsp;
          <span className="dot bad" /> error anomaly
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="recon-chart-svg">
        {/* fill gradient */}
        <defs>
          <linearGradient id="recon-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* grid */}
        {yTicks.map((v, i) => (
          <g key={i}>
            <line
              x1={PAD_L} x2={W - PAD_R}
              y1={yScale(v)} y2={yScale(v)}
              stroke="#334155" strokeDasharray="2 4" strokeWidth={1}
            />
            <text
              x={PAD_L - 6} y={yScale(v) + 4}
              textAnchor="end" fontSize="10" fill="#94a3b8"
            >
              {fmtCompact(v)}
            </text>
          </g>
        ))}
        {/* x labels */}
        {xTickIdxs.map((idx) => (
          <text
            key={idx}
            x={xScale(idx)} y={H - 10}
            textAnchor="middle" fontSize="10" fill="#94a3b8"
          >
            {data.points[idx].date.slice(5)}
          </text>
        ))}
        {/* area fill */}
        <path d={fillPath} fill="url(#recon-fill)" />
        {/* line */}
        <path d={linePath} stroke="#38bdf8" strokeWidth={2} fill="none" />
        {/* anomaly markers */}
        {data.markers.map((m, i) => (
          <g key={i}>
            <circle
              cx={xScale(m.idx)} cy={yScale(m.balance)}
              r={4}
              fill={m.severity === "error" ? "#ef4444" : "#f59e0b"}
              stroke="#0f172a" strokeWidth={1.5}
            >
              <title>{m.message}</title>
            </circle>
          </g>
        ))}
      </svg>
    </div>
  );
}

interface SeriesPoint { date: string; balance: number }
interface Marker { idx: number; balance: number; severity: string; message: string }
interface Series {
  points: SeriesPoint[];
  markers: Marker[];
  min: number;
  max: number;
}

function buildSeries(statement: StatementResult): Series {
  // Reconstruct the running balance by walking transactions in date
  // order. Bank's published "ending balance" is the anchor.
  const txns: Transaction[] = [...(statement.transactions ?? [])]
    .sort((a, b) => a.date.localeCompare(b.date));
  let running = statement.summary.beginning_balance;
  const points: SeriesPoint[] = [
    { date: statement.account.period.start, balance: running },
  ];
  txns.forEach((t) => {
    if (t.deposit != null) running += t.deposit;
    if (t.withdrawal != null) running -= t.withdrawal;
    points.push({ date: t.date, balance: round2(running) });
  });

  let min = Infinity;
  let max = -Infinity;
  for (const p of points) {
    if (p.balance < min) min = p.balance;
    if (p.balance > max) max = p.balance;
  }
  if (min === Infinity) { min = 0; max = 1; }

  // Map anomaly transaction_index to a point index.
  const markers: Marker[] = [];
  (statement._anomalies || []).forEach((a: Anomaly) => {
    if (a.transaction_index == null) return;
    const txIdx = a.transaction_index;
    const allTx = statement.transactions ?? [];
    if (txIdx < 0 || txIdx >= allTx.length) return;
    const t = allTx[txIdx];
    const ptIdx = points.findIndex((p) => p.date === t.date) + 1;
    if (ptIdx <= 0 || ptIdx >= points.length) return;
    markers.push({
      idx: ptIdx,
      balance: points[ptIdx].balance,
      severity: a.severity,
      message: a.message.slice(0, 200),
    });
  });

  return { points, markers, min, max };
}

function fmtCompact(n: number): string {
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}k`;
  return `$${n.toFixed(0)}`;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
