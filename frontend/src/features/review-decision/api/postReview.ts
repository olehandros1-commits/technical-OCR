import { V1 } from "@/shared/api";
import type { Decision } from "@/entities/review";

export async function postReview(payload: {
  statement_key: string;
  tx_index: number;
  decision: Decision;
  reviewer?: string;
  note?: string;
}): Promise<{ id: number; status: string }> {
  const r = await fetch(`${V1}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`postReview failed: ${r.status}`);
  return r.json();
}
