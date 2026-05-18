import { V1 } from "@/shared/api";
import type { PipelineEvent } from "@/entities/pipeline-event";

export function streamJobEvents(
  jobId: string,
  onEvent: (ev: PipelineEvent) => void,
  onDone: () => void,
  onError: (e: Event) => void,
): () => void {
  const es = new EventSource(`${V1}/extraction/jobs/${jobId}/events`);
  const seen = new Set<string>();
  let doneFired = false;

  const dispatch = (wire: { event?: string; data?: Record<string, unknown>; ts?: number }) => {
    if (doneFired) return;
    const eventName = wire.event ?? "message";
    const key = `${eventName}|${JSON.stringify(wire.data ?? {})}`;
    if (seen.has(key)) return;
    seen.add(key);

    onEvent({
      event: eventName,
      data: (wire.data ?? {}) as Record<string, unknown>,
      ts: wire.ts ?? Date.now() / 1000,
    });

    if (eventName === "done") {
      doneFired = true;
      onDone();
      es.close();
    }
  };

  es.onmessage = (e) => {
    try {
      dispatch(JSON.parse(e.data));
    } catch (err) {
      console.warn("malformed event", err, e.data);
    }
  };

  es.addEventListener("done", () => {
    if (!doneFired) {
      doneFired = true;
      onDone();
      es.close();
    }
  });

  es.onerror = (e) => {
    if (doneFired) {
      es.close();
      return;
    }
    if (es.readyState === EventSource.CLOSED) {
      onError(e);
    } else {
      console.debug("SSE transient error; EventSource auto-reconnecting", e);
    }
  };

  return () => {
    doneFired = true;
    es.close();
  };
}
