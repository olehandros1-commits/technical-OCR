import { V1, _formData } from "@/shared/api";
import type { ExtractOptions } from "@/shared/api";

export async function createJob(opts: ExtractOptions): Promise<string> {
  const r = await fetch(`${V1}/extraction/jobs`, {
    method: "POST",
    body: _formData(opts),
  });
  if (!r.ok) throw new Error(`createJob failed: ${r.status} ${await r.text()}`);
  const j = await r.json();
  return j.job_id as string;
}
