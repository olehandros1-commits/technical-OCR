import { useEffect, useRef } from "react";
import type { PipelineEvent } from "@/entities/pipeline-event";

interface Props {
  events: PipelineEvent[];
  running: boolean;
}

export function LiveProgress({ events, running }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  const t0 = events[0]?.ts ?? 0;

  return (
    <section className="progress">
      <div className="progress-header">
        <h3>Pipeline events</h3>
        {running && <span className="pill running">running</span>}
      </div>
      <div className="progress-log">
        {events.map((e, i) => {
          const elapsed = (e.ts - t0).toFixed(2);
          return (
            <div key={i} className={`log-line log-${e.event}`}>
              <span className="t">{elapsed}s</span>
              <span className="n">{e.event}</span>
              <span className="d">{summarize(e.data)}</span>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </section>
  );
}

function summarize(data: Record<string, unknown>): string {
  // Compact one-liner for the most common event payloads.
  const keys = ["label", "count", "bank", "last4", "period", "issues",
                "ok", "error", "elapsed_s", "statement_count", "by_kind"];
  const parts: string[] = [];
  for (const k of keys) {
    if (k in data) {
      const v = data[k];
      parts.push(`${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
    }
  }
  return parts.length > 0 ? parts.join(" ") : JSON.stringify(data);
}
