export const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
export const V1 = `${BASE}/api/v1`;

export interface ExtractOptions {
  pdf: File;
  txt?: File | null;
  backend: import("@/entities/tier").Backend | "";
  tier?: import("@/entities/tier").Tier | "";
  ocrMode: import("@/entities/tier").OcrMode;
  enrich: boolean;
  parallel: number;
}

export function _formData(opts: ExtractOptions): FormData {
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
