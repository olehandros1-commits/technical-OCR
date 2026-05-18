import { V1, _formData } from "@/shared/api";
import type { ExtractOptions, Telemetry } from "@/shared/api";
import type { StatementResult } from "@/entities/statement";

export async function extractBlocking(
  opts: ExtractOptions,
): Promise<{ results: StatementResult[]; telemetry: Telemetry }> {
  const r = await fetch(`${V1}/extraction/extract`, {
    method: "POST",
    body: _formData(opts),
  });
  if (!r.ok) throw new Error(`extract failed: ${r.status} ${await r.text()}`);
  return r.json();
}
