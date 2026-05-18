export interface PipelineEvent {
  event: string;
  data: Record<string, unknown>;
  ts: number;
}
