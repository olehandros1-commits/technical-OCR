import { V1, _formData } from "@/shared/api";
import type { ExtractOptions } from "@/shared/api";

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
