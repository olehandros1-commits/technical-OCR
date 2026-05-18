import { useMemo, useState } from "react";
import type { Transaction, TxCategory } from "../model/types";

interface Props {
  transactions: Transaction[];
  selectedIndex?: number | null;
  onSelect?: (index: number, description: string) => void;
}

export function TransactionsTable({ transactions, selectedIndex, onSelect }: Props) {
  const [side, setSide] = useState<"all" | "deposit" | "withdrawal">("all");
  const [category, setCategory] = useState<TxCategory | "all">("all");
  const [minConf, setMinConf] = useState(0);
  const [search, setSearch] = useState("");

  const categories = useMemo(
    () => Array.from(new Set(transactions.map((t) => t.category).filter(Boolean))) as TxCategory[],
    [transactions],
  );

  const filtered = useMemo(() => {
    return transactions
      .map((t, originalIndex) => ({ t, originalIndex }))
      .filter(({ t }) => {
        if (side === "deposit" && t.deposit === null) return false;
        if (side === "withdrawal" && t.withdrawal === null) return false;
        if (category !== "all" && t.category !== category) return false;
        if (minConf > 0 && (t.confidence ?? 1) < minConf) return false;
        if (search && !t.description.toLowerCase().includes(search.toLowerCase()))
          return false;
        return true;
      });
  }, [transactions, side, category, minConf, search]);

  return (
    <div className="tx-table-wrapper">
      <div className="tx-filters">
        <div className="seg">
          {(["all", "deposit", "withdrawal"] as const).map((s) => (
            <button
              key={s}
              className={s === side ? "on" : ""}
              onClick={() => setSide(s)}
            >
              {s}
            </button>
          ))}
        </div>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as TxCategory | "all")}
        >
          <option value="all">all categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label>
          <span>min conf</span>
          <input
            type="range"
            min={0} max={1} step={0.05}
            value={minConf}
            onChange={(e) => setMinConf(Number(e.target.value))}
          />
          <span>{minConf.toFixed(2)}</span>
        </label>
        <input
          type="search"
          placeholder="search description..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="tx-count">
          {filtered.length} / {transactions.length}
        </span>
      </div>
      <div className="tx-table-scroll">
        <table className="tx-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Description</th>
              <th>Category</th>
              <th>Vendor</th>
              <th className="num">Deposit</th>
              <th className="num">Withdrawal</th>
              <th className="num">Conf.</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(({ t, originalIndex }) => {
              const isSelected = selectedIndex === originalIndex;
              const lowConf = (t.confidence ?? 1) < 0.5;
              const rowClass = [
                lowConf ? "low-conf" : "",
                isSelected ? "tx-row-selected" : "",
              ].filter(Boolean).join(" ");
              return (
                <tr
                  key={originalIndex}
                  className={rowClass}
                  onClick={() => onSelect?.(originalIndex, t.description)}
                  style={{ cursor: onSelect ? "pointer" : undefined }}
                >
                  <td>{t.date}</td>
                  <td className="desc">{t.description}</td>
                  <td>{t.category && <span className="cat">{t.category}</span>}</td>
                  <td>
                    {t.vendor && (
                      <span className="vendor-chip" title={t._vendor_domain ?? t.vendor}>
                        {t._vendor_logo && (
                          <img
                            src={t._vendor_logo}
                            alt=""
                            className="vendor-logo"
                            loading="lazy"
                            onError={(e) => (e.currentTarget.style.display = "none")}
                          />
                        )}
                        <span>{t._vendor_canonical ?? t.vendor}</span>
                      </span>
                    )}
                  </td>
                  <td className="num">
                    {t.deposit !== null ? `$${t.deposit.toLocaleString()}` : ""}
                  </td>
                  <td className="num">
                    {t.withdrawal !== null ? `$${t.withdrawal.toLocaleString()}` : ""}
                  </td>
                  <td className="num">
                    {t.confidence !== null ? t.confidence.toFixed(2) : "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
