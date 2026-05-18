// Thin client for the FastAPI backend at /extract /jobs /reviews.
// Uses the native fetch + EventSource APIs to keep deps minimal.

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
  const r = await fetch(`${BASE}/tiers`);
  if (!r.ok) return [];
  const j = await r.json();
  return j.tiers ?? [];
}

function _formData(opts: ExtractOptions): FormData {
  const fd = new FormData();
  fd.append("pdf", opts.pdf);
  if (opts.txt) fd.append("txt", opts.txt);
  // When a tier is set, omit `backend` entirely so the server uses the
  // tier's backend unambiguously. Sending the stale form default would
  // collide with the tier selection (cloud vs local mix-up).
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

/** Synchronous extraction (best for small statements). */
export async function extractBlocking(
  opts: ExtractOptions,
): Promise<{ results: StatementResult[]; telemetry: Telemetry }> {
  const r = await fetch(`${BASE}/extract`, {
    method: "POST",
    body: _formData(opts),
  });
  if (!r.ok) throw new Error(`extract failed: ${r.status} ${await r.text()}`);
  return r.json();
}

/** Start an async job. Returns job_id you stream via streamJobEvents. */
export async function createJob(opts: ExtractOptions): Promise<string> {
  const r = await fetch(`${BASE}/jobs`, {
    method: "POST",
    body: _formData(opts),
  });
  if (!r.ok) throw new Error(`createJob failed: ${r.status} ${await r.text()}`);
  const j = await r.json();
  return j.job_id as string;
}

/** Read final result of an async job. Returns null while still running. */
export async function getJobResult(
  jobId: string,
): Promise<{ results: StatementResult[]; telemetry: Telemetry } | null> {
  const r = await fetch(`${BASE}/jobs/${jobId}`);
  if (r.status === 202) return null; // still running
  if (!r.ok) throw new Error(`getJob failed: ${r.status}`);
  return r.json();
}

/** Stream pipeline events for a job via Server-Sent Events.
 *
 * The server emits events with both a named directive AND a generic
 * 'message' payload. We listen on `onmessage` as a catch-all so any new
 * event types added on the backend show up automatically without a
 * frontend code change.
 */
export function streamJobEvents(
  jobId: string,
  onEvent: (ev: PipelineEvent) => void,
  onDone: () => void,
  onError: (e: Event) => void,
): () => void {
  const es = new EventSource(`${BASE}/jobs/${jobId}/events`);

  es.onmessage = (e) => {
    try {
      const wire = JSON.parse(e.data);
      // Wire payload: { event, data, ts }
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

  // Also handle the named 'done' event in case browsers prefer it.
  es.addEventListener("done", () => {
    onDone();
    es.close();
  });
  es.onerror = onError;
  return () => es.close();
}

/** Trigger an Excel-workbook download for the same inputs. */
export async function downloadXlsx(opts: ExtractOptions, filename = "statements.xlsx"): Promise<void> {
  const r = await fetch(`${BASE}/export/xlsx`, {
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

/** Ask the backend's CHEAP-tier LLM to explain a flagged anomaly in
 *  plain English. Returns 1-3 sentences + one suggested action. */
export async function explainAnomaly(
  anomaly: unknown,
  transaction: unknown | null = null,
  context: unknown[] = [],
): Promise<ExplainResult> {
  const r = await fetch(`${BASE}/explain`, {
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
  const r = await fetch(`${BASE}/diff`, {
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
  const r = await fetch(`${BASE}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`postReview failed: ${r.status}`);
  return r.json();
}
