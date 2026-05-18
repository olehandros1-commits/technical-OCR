import type { Telemetry } from "@/shared/api";

export function TelemetryStrip({ t }: { t: Telemetry }) {
  return (
    <section className="telemetry">
      <Metric label="LLM calls" value={t.total_calls.toString()} />
      <Metric label="Input tokens" value={fmt(t.total_input_tokens)} />
      <Metric label="Output tokens" value={fmt(t.total_output_tokens)} />
      <Metric label="Cache read" value={fmt(t.total_cache_read)} />
      <Metric label="Elapsed" value={`${(t.total_elapsed_s ?? 0).toFixed(1)}s`} />
      <Metric
        label="Cost (USD)"
        value={`$${(t.total_cost_usd ?? 0).toFixed(4)}`}
        emphasis
      />
    </section>
  );
}

function Metric({
  label, value, emphasis,
}: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className={`metric ${emphasis ? "emphasis" : ""}`}>
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
    </div>
  );
}

function fmt(n: number | undefined): string {
  if (n === undefined) return "-";
  return n.toLocaleString();
}
