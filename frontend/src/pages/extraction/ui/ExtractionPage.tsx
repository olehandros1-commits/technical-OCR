import { useCallback, useMemo, useState } from "react";
import { createJob, getJobResult, streamJobEvents } from "@/features/extract-job";
import { downloadXlsx } from "@/features/download-xlsx";
import { FileDropzone } from "@/features/upload-file";
import { Toolbar } from "@/features/tier-select";
import { LiveProgress, TelemetryStrip } from "@/widgets/pipeline-events";
import { StatementCard } from "@/widgets/statement-card";
import { ReviewQueue } from "@/widgets/review-queue";
import { TimeSeriesDashboard } from "@/widgets/time-series-dashboard";
import { DiffView } from "@/widgets/diff-view";
import { PdfPreview } from "@/widgets/pdf-preview";
import type { Backend, OcrMode } from "@/entities/tier";
import type { PipelineEvent } from "@/entities/pipeline-event";
import type { StatementResult } from "@/entities/statement";
import type { Telemetry } from "@/shared/api";
import type { ReviewItem } from "@/entities/review";
import { REVIEW_THRESHOLD } from "@/shared/config";

export function ExtractionPage() {
  const [selectedTxText, setSelectedTxText] = useState<string | null>(null);
  const [pdf, setPdf] = useState<File | null>(null);
  const [txt, setTxt] = useState<File | null>(null);
  const [backend, setBackend] = useState<Backend>("anthropic");
  const [tier, setTier] = useState<"" | "premium" | "balanced" | "cheap" | "local">("balanced");
  const [ocrMode, setOcrMode] = useState<OcrMode>("auto");
  // Off by default to keep cold-cache demos cheap (each enrich call is
  // ~$0.10-0.30 per statement on Sonnet). Flip on in the Toolbar when
  // categorisation + confidence are actually needed.
  const [enrich, setEnrich] = useState(false);
  const [parallel, setParallel] = useState(2);

  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [results, setResults] = useState<StatementResult[]>([]);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [running, setRunning] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const run = useCallback(async () => {
    if (!pdf && !txt) return;
    setEvents([]);
    setResults([]);
    setTelemetry(null);
    setRunning(true);
    setErrorMsg(null);
    try {
      const jobId = await createJob({
        pdf: pdf ?? undefined, txt: txt ?? undefined,
        backend, tier, ocrMode, enrich, parallel,
      });
      streamJobEvents(
        jobId,
        (ev) => setEvents((prev) => [...prev, ev]),
        async () => {
          const r = await getJobResult(jobId);
          if (r) {
            setResults(r.results);
            setTelemetry(r.telemetry);
          }
          setRunning(false);
        },
        (e) => {
          console.error(e);
          setErrorMsg("Lost connection to job stream");
          setRunning(false);
        },
      );
    } catch (err) {
      setErrorMsg(String(err));
      setRunning(false);
    }
  }, [pdf, txt, backend, ocrMode, enrich, parallel]);

  // HITL review queue: low confidence + warn/error anomalies.
  const reviewQueue = useMemo<ReviewItem[]>(() => {
    const out: ReviewItem[] = [];
    results.forEach((r) => {
      const key = `${r.account.period.start}_${r.account.account_last4 ?? "none"}`;
      r.transactions.forEach((t, tIdx) => {
        if (t.confidence !== null && t.confidence < REVIEW_THRESHOLD) {
          out.push({
            statementKey: key,
            txIndex: tIdx,
            date: t.date,
            description: t.description,
            amount: (t.deposit ?? t.withdrawal ?? 0),
            side: t.deposit !== null ? "deposit" : "withdrawal",
            confidence: t.confidence,
            reason: `low confidence (${t.confidence.toFixed(2)})`,
          });
        }
      });
      r._anomalies.forEach((an) => {
        if ((an.severity === "warn" || an.severity === "error") && an.transaction_index !== null) {
          const t = r.transactions[an.transaction_index];
          if (!t) return;
          out.push({
            statementKey: key,
            txIndex: an.transaction_index,
            date: t.date,
            description: t.description,
            amount: (t.deposit ?? t.withdrawal ?? 0),
            side: t.deposit !== null ? "deposit" : "withdrawal",
            confidence: t.confidence,
            reason: `${an.kind}: ${an.message}`,
          });
        }
      });
    });
    return out;
  }, [results]);

  const reconciledCount = results.filter((r) => r._reconciliation?.ok).length;

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Bank Statement Extractor</h1>
          <span className="tagline">
            dobs.ai technical demo · React + TypeScript + FastAPI · SSE live stream
          </span>
        </div>
        <a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noreferrer"
          className="link-btn"
        >
          OpenAPI docs
        </a>
      </header>

      <Toolbar
        backend={backend} setBackend={setBackend}
        tier={tier} setTier={setTier}
        ocrMode={ocrMode} setOcrMode={setOcrMode}
        enrich={enrich} setEnrich={setEnrich}
        parallel={parallel} setParallel={setParallel}
      />

      <FileDropzone
        pdf={pdf} setPdf={setPdf}
        txt={txt} setTxt={setTxt}
        onRun={run}
        canRun={(!!pdf || !!txt) && !running}
        running={running}
      />

      {errorMsg && <div className="error-banner">{errorMsg}</div>}

      {(events.length > 0 || running) && (
        <LiveProgress events={events} running={running} />
      )}

      {telemetry && telemetry.total_calls > 0 && (
        <TelemetryStrip t={telemetry} />
      )}

      {results.length > 0 && (
        <section className="results">
          <div className="results-header">
            <h2>Results</h2>
            <div className="results-actions">
              <span className="results-summary">
                <strong>{results.length}</strong> statement{results.length > 1 ? "s" : ""},{" "}
                <strong className={reconciledCount === results.length ? "ok" : "bad"}>
                  {reconciledCount}/{results.length} reconciled
                </strong>,{" "}
                <strong>
                  {results.reduce((n, r) => n + r.transactions.length, 0)}
                </strong>{" "}
                transactions
              </span>
              {pdf && (
                <button
                  className="xlsx-btn"
                  onClick={() => downloadXlsx(
                    { pdf, txt: txt ?? undefined, backend, tier, ocrMode, enrich, parallel },
                    `${pdf.name.replace(/\.pdf$/i, '')}.xlsx`,
                  )}
                  title="Multi-sheet Excel workbook with live SUMIF formulas, continuity audit, and conditional formatting"
                >
                  Download Excel (with formulas)
                </button>
              )}
            </div>
          </div>

          {reviewQueue.length > 0 && <ReviewQueue items={reviewQueue} />}

          <TimeSeriesDashboard statements={results} />

          <DiffView results={results} />

          <div className="results-grid">
            <div className="statement-list">
              {results.map((r) => (
                <StatementCard
                  key={`${r.account.period.start}-${r.account.account_last4}`}
                  statement={r}
                  onTxSelect={setSelectedTxText}
                />
              ))}
            </div>
            <PdfPreview file={pdf} targetText={selectedTxText} />
          </div>
        </section>
      )}
    </div>
  );
}
