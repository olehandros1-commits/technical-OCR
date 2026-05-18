import { useState } from "react";
import { postReview } from "../api";
import type { Decision, ReviewItem } from "../types";

interface Props {
  items: ReviewItem[];
}

export function ReviewQueue({ items }: Props) {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});

  const handle = async (item: ReviewItem, decision: Decision) => {
    const key = itemKey(item);
    setSubmitting((s) => ({ ...s, [key]: true }));
    try {
      await postReview({
        statement_key: item.statementKey,
        tx_index: item.txIndex,
        decision,
        reviewer: "ui",
      });
      setDecisions((d) => ({ ...d, [key]: decision }));
    } catch (e) {
      console.error(e);
      alert(`Failed to record decision: ${e}`);
    } finally {
      setSubmitting((s) => ({ ...s, [key]: false }));
    }
  };

  return (
    <section className="review-queue">
      <div className="review-header">
        <h3>Human review queue</h3>
        <span className="review-count">{items.length} item{items.length > 1 ? "s" : ""}</span>
      </div>
      <p className="review-help">
        Transactions flagged by low confidence or warn/error anomalies. Approve to
        accept the extraction, reject to mark for manual fix.
      </p>
      <div className="review-list">
        {items.slice(0, 80).map((item) => {
          const key = itemKey(item);
          const decided = decisions[key];
          return (
            <div key={key} className={`review-item ${decided ? `decided ${decided}` : ""}`}>
              <div className="review-meta">
                <span className="review-date">{item.date}</span>
                <span className="review-amount">
                  ${item.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}{" "}
                  <span className="review-side">{item.side[0].toUpperCase()}</span>
                </span>
              </div>
              <div className="review-desc">{item.description}</div>
              <div className="review-reason">{item.reason}</div>
              <div className="review-actions">
                {decided ? (
                  <span className={`decision-badge ${decided}`}>{decided.toUpperCase()}</span>
                ) : (
                  <>
                    <button
                      className="btn-approve"
                      disabled={submitting[key]}
                      onClick={() => handle(item, "approve")}
                    >
                      Approve
                    </button>
                    <button
                      className="btn-reject"
                      disabled={submitting[key]}
                      onClick={() => handle(item, "reject")}
                    >
                      Reject
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
        {items.length > 80 && (
          <div className="review-overflow">
            +{items.length - 80} more not shown
          </div>
        )}
      </div>
    </section>
  );
}

function itemKey(i: ReviewItem): string {
  return `${i.statementKey}#${i.txIndex}`;
}
