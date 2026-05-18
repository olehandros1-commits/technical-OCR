import { V1 } from "@/shared/api";
import type { PipelineEvent } from "@/entities/pipeline-event";

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
