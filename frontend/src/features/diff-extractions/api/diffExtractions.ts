import { V1 } from "@/shared/api";

export interface ExtractionDiff {
  only_in_a_count: number;
  only_in_b_count: number;
  changed_count: number;
  common_count: number;
  only_in_a: unknown[];
  only_in_b: unknown[];
  changed: { key: unknown[]; fields: Record<string, { a: unknown; b: unknown }> }[];
  summary_deltas: Record<string, { a: unknown; b: unknown; delta: number | null }>;
}

export async function diffExtractions(a: unknown, b: unknown): Promise<ExtractionDiff> {
  const r = await fetch(`${V1}/diff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ a, b }),
  });
  if (!r.ok) throw new Error(`diff failed: ${r.status}`);
  return r.json();
}
