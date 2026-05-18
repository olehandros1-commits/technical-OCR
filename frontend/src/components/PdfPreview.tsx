import { useEffect, useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Pin the worker to a versioned CDN copy that matches the bundled pdfjs.
// Self-hosted alternative: copy
// node_modules/pdfjs-dist/build/pdf.worker.min.mjs into /public and point
// workerSrc at '/pdf.worker.min.mjs'.
pdfjs.GlobalWorkerOptions.workerSrc =
  `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface Props {
  file: File | null;
}

/** Embedded PDF.js viewer with paging + zoom. Drives nothing else --
 *  pure visual aid so reviewers can compare a transaction row in the
 *  extracted table against the source page. */
export function PdfPreview({ file }: Props) {
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(0.9);

  // Recreate object URL whenever the file changes so the Document remounts
  // cleanly (react-pdf caches by URL identity).
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => {
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [url]);

  if (!file || !url) return null;

  return (
    <aside className="pdf-preview">
      <div className="pdf-toolbar">
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>‹</button>
        <span className="pdf-pos">page {page} / {numPages || "?"}</span>
        <button onClick={() => setPage(p => Math.min(numPages || p + 1, p + 1))}
                disabled={page >= numPages}>›</button>
        <span className="pdf-spacer" />
        <button onClick={() => setScale(s => Math.max(0.4, s - 0.1))}>-</button>
        <span className="pdf-zoom">{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale(s => Math.min(2.0, s + 0.1))}>+</button>
      </div>
      <div className="pdf-frame">
        <Document
          file={url}
          onLoadSuccess={(pdf) => setNumPages(pdf.numPages)}
          onLoadError={(err) => console.error("pdf load error", err)}
          loading={<div className="pdf-loading">Loading PDF…</div>}
          error={<div className="pdf-error">Couldn’t render PDF preview (this is just visual; extraction still works).</div>}
        >
          <Page
            pageNumber={page}
            scale={scale}
            renderTextLayer
            renderAnnotationLayer={false}
          />
        </Document>
      </div>
    </aside>
  );
}
