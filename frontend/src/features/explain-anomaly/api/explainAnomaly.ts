import { V1 } from "@/shared/api";

export interface ExplainResult {
  summary: string;
  suggested_action: string;
}

export async function explainAnomaly(
  anomaly: unknown,
  transaction: unknown | null = null,
  context: unknown[] = [],
): Promise<ExplainResult> {
  const r = await fetch(`${V1}/reviews/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      anomaly,
      transaction,
      context_transactions: context,
    }),
  });
  if (!r.ok) throw new Error(`explain failed: ${r.status}`);
  return r.json();
}
