import { useMemo } from "react";
import type { StatementResult, TxCategory } from "../types";

interface Props {
  statements: StatementResult[];
}

/** Cross-statement analytics dashboard.
 *
 *  When the user uploads or extracts multiple statements from the same
 *  account (e.g. 10 monthly Ixonia statements), this view aggregates:
 *    - net cash flow per period
 *    - top 5 vendors by total outflow
 *    - category breakdown across all periods
 *    - largest single transactions
 *
 *  Pure client-side compute from the results array; no extra API calls.
 *  Renders nothing when fewer than 2 statements -- single-statement
 *  analytics live in the StatementCard already.
 */
export function TimeSeriesDashboard({ statements }: Props) {
  const ts = useMemo(() => aggregate(statements), [statements]);
  if (ts.periods.length < 2) return null;

  return (
    <section className="ts-dashboard">
      <h3>
        Time-series analytics
        <span className="muted">  ·  {ts.periods.length} periods · {ts.totalTx.toLocaleString()} transactions</span>
      </h3>

      <div className="ts-grid">
        <NetCashFlow periods={ts.periods} />
        <TopVendors items={ts.topVendors} />
        <CategoryBreakdown items={ts.categoryTotals} />
        <BiggestTx items={ts.biggestTx} />
      </div>
    </section>
  );
}

interface Period {
  label: string;          // "Apr 2025"
  inflow: number;
  outflow: number;
  net: number;
}
interface VendorTotal { vendor: string; total: number; count: number }
interface CatTotal { category: string; total: number; count: number }
interface BigTx {
  date: string; description: string; side: string; amount: number;
}

interface Aggregated {
  periods: Period[];
  topVendors: VendorTotal[];
  categoryTotals: CatTotal[];
  biggestTx: BigTx[];
  totalTx: number;
}

function aggregate(stmts: StatementResult[]): Aggregated {
  const periods: Period[] = [];
  const vendorMap: Record<string, VendorTotal> = {};
  const catMap: Record<string, CatTotal> = {};
  const biggestPool: BigTx[] = [];
  let totalTx = 0;

  for (const s of stmts) {
    const periodLabel = monthLabel(s.account.period.start);
    let inflow = 0, outflow = 0;
    for (const t of s.transactions) {
      totalTx += 1;
      if (t.deposit != null) inflow += t.deposit;
      if (t.withdrawal != null) outflow += t.withdrawal;
      const vKey = (t._vendor_canonical ?? t.vendor)?.trim();
      if (vKey && t.withdrawal != null) {
        if (!vendorMap[vKey]) vendorMap[vKey] = { vendor: vKey, total: 0, count: 0 };
        vendorMap[vKey].total += t.withdrawal;
        vendorMap[vKey].count += 1;
      }
      const cat: TxCategory = t.category ?? "OTHER";
      const amount = (t.deposit ?? t.withdrawal ?? 0);
      if (!catMap[cat]) catMap[cat] = { category: cat, total: 0, count: 0 };
      catMap[cat].total += amount;
      catMap[cat].count += 1;
      biggestPool.push({
        date: t.date,
        description: t.description.slice(0, 60),
        side: t.deposit != null ? "deposit" : "withdrawal",
        amount,
      });
    }
    periods.push({
      label: periodLabel,
      inflow,
      outflow,
      net: inflow - outflow,
    });
  }

  periods.sort((a, b) => a.label.localeCompare(b.label));
  const topVendors = Object.values(vendorMap)
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);
  const categoryTotals = Object.values(catMap)
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);
  const biggestTx = biggestPool
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 8);
  return { periods, topVendors, categoryTotals, biggestTx, totalTx };
}

function monthLabel(iso: string): string {
  // Stable sortable label "2025-04" rather than "Apr 2025"; display
  // formatter does the pretty thing.
  return iso.slice(0, 7);
}

function pretty(label: string): string {
  // "2025-04" -> "Apr 2025"
  try {
    const [y, m] = label.split("-").map(Number);
    const d = new Date(y, (m ?? 1) - 1, 1);
    return d.toLocaleString(undefined, { month: "short", year: "numeric" });
  } catch { return label; }
}

function fmt$(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function NetCashFlow({ periods }: { periods: Period[] }) {
  const max = Math.max(...periods.map((p) => Math.max(p.inflow, p.outflow))) || 1;
  return (
    <div className="ts-card">
      <h4>Net cash flow per period</h4>
      <div className="ts-bars">
        {periods.map((p) => {
          const inH = (p.inflow / max) * 80;
          const outH = (p.outflow / max) * 80;
          return (
            <div key={p.label} className="ts-bar-col" title={
              `${pretty(p.label)}\nIn ${fmt$(p.inflow)} · Out ${fmt$(p.outflow)} · Net ${fmt$(p.net)}`
            }>
              <div className="bars">
                <div className="bar in"  style={{ height: `${inH}px`  }} />
                <div className="bar out" style={{ height: `${outH}px` }} />
              </div>
              <div className={`ts-net ${p.net >= 0 ? "pos" : "neg"}`}>
                {p.net >= 0 ? "+" : ""}{fmt$(p.net)}
              </div>
              <div className="ts-label">{pretty(p.label).slice(0, 3)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TopVendors({ items }: { items: VendorTotal[] }) {
  return (
    <div className="ts-card">
      <h4>Top vendors by outflow</h4>
      {items.length === 0 ? (
        <p className="muted small">No vendor data (enable enrich to populate).</p>
      ) : (
        <ul className="ts-list">
          {items.map((v) => (
            <li key={v.vendor}>
              <span className="ts-name">{v.vendor}</span>
              <span className="ts-val">{fmt$(v.total)} <small>·  {v.count}x</small></span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CategoryBreakdown({ items }: { items: CatTotal[] }) {
  const sum = items.reduce((acc, c) => acc + c.total, 0) || 1;
  return (
    <div className="ts-card">
      <h4>By category</h4>
      <ul className="ts-list">
        {items.map((c) => {
          const pct = (c.total / sum) * 100;
          return (
            <li key={c.category}>
              <span className="ts-name"><span className="cat">{c.category}</span></span>
              <span className="ts-val">{fmt$(c.total)} <small>· {pct.toFixed(0)}%</small></span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BiggestTx({ items }: { items: BigTx[] }) {
  return (
    <div className="ts-card">
      <h4>Biggest transactions</h4>
      <ul className="ts-list">
        {items.map((t, i) => (
          <li key={i}>
            <span className="ts-name">
              <span className="muted small">{t.date}</span> {t.description}
            </span>
            <span className={`ts-val ${t.side}`}>{fmt$(t.amount)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
