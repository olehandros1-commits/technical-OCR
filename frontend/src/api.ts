import type {
  Backend,
  Decision,
  OcrMode,
  PipelineEvent,
  StatementResult,
  Telemetry,
  Tier,
  TierInfo,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const V1 = `${BASE}/api/v1`;

export interface ExtractOptions {
  pdf: File;
  txt?: File | null;
  backend: Backend | "";
  tier?: Tier | "";
  ocrMode: OcrMode;
  enrich: boolean;
  parallel: number;
}

export async function listTiers(): Promise<TierInfo[]> {
  const r = await fetch(`${V1}/telemetry/tiers`);
  if (!r.ok) return [];
  const j = await r.json();
  return j.tiers ?? [];
}

function _formData(opts: ExtractOptions): FormData {
  const fd = new FormData();
  fd.append("pdf", opts.pdf);
  if (opts.txt) fd.append("txt", opts.txt);
  if (opts.tier) {
    fd.append("tier", opts.tier);
  } else {
    fd.append("backend", opts.backend || "");
  }
  fd.append("ocr_mode", opts.ocrMode);
  fd.append("enrich", String(opts.enrich));
  fd.append("parallel", String(opts.parallel));
  return fd;
}

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

export async function createJob(opts: ExtractOptions): Promise<string> {
  const r = await fetch(`${V1}/extraction/jobs`, {
    method: "POST",
    body: _formData(opts),
  });
  if (!r.ok) throw new Error(`createJob failed: ${r.status} ${await r.text()}`);
  const j = await r.json();
  return j.job_id as string;
}

export async function getJobResult(
  jobId: string,
): Promise<{ results: StatementResult[]; telemetry: Telemetry } | null> {
  const r = await fetch(`${V1}/extraction/jobs/${jobId}`);
  if (r.status === 202) return null;
  if (!r.ok) throw new Error(`getJob failed: ${r.status}`);
  return r.json();
}

export function streamJobEvents(
  jobId: string,
  onEvent: (ev: PipelineEvent) => void,
  onDone: () => void,
  onError: (e: Event) => void,
): () => void {
  const es = new EventSource(`${V1}/extraction/jobs/${jobId}/events`);

  es.onmessage = (e) => {
    try {
      const wire = JSON.parse(e.data);
      onEvent({
        event: wire.event ?? "message",
        data: wire.data ?? {},
        ts: wire.ts ?? Date.now() / 1000,
      });
      if (wire.event === "done") {
        onDone();
        es.close();
      }
    } catch (err) {
      console.warn("malformed event", err, e.data);
    }
  };

  es.addEventListener("done", () => {
    onDone();
    es.close();
  });
  es.onerror = onError;
  return () => es.close();
}

export async function downloadXlsx(opts: ExtractOptions, filename = "statements.xlsx"): Promise<void> {
  const r = await fetch(`${V1}/extraction/export/xlsx`, {
    method: "POST",
    body: _formData(opts),
  });
  if (!r.ok) throw new Error(`xlsx export failed: ${r.status}`);
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

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

export interface ExtractionDiff {
  only_in_a_count: number;
  only_in_b_count: number;
  changed_count: number;
  common_count: number;
  only_in_a: any[];
  only_in_b: any[];
  changed: { key: any[]; fields: Record<string, { a: any; b: any }> }[];
  summary_deltas: Record<string, { a: any; b: any; delta: number | null }>;
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
