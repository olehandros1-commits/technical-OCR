import { V1 } from "@/shared/api";
import type { Telemetry } from "@/shared/api";
import type { StatementResult } from "@/entities/statement";

export async function getJobResult(
  jobId: string,
): Promise<{ results: StatementResult[]; telemetry: Telemetry } | null> {
  const r = await fetch(`${V1}/extraction/jobs/${jobId}`);
  if (r.status === 202) return null;
  if (!r.ok) throw new Error(`getJob failed: ${r.status}`);
  return r.json();
}
