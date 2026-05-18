import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { tryMatch, usePdfHighlight, usePdfTextIndex } from "@/features/pdf-text-search";

pdfjs.GlobalWorkerOptions.workerSrc =
  `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface Props {
  file: File | null;
  targetText?: string | null;
}

export function PdfPreview({ file, targetText }: Props) {
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(0.9);
  const [toast, setToast] = useState<string | null>(null);

  const pageRef = useRef<HTMLDivElement | null>(null);

  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => {
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [url]);

  const pageTextsRef = usePdfTextIndex(url, numPages);
  const applyHighlight = usePdfHighlight(pageRef, page);

  useEffect(() => {
    if (!targetText || !url) return;
    const texts = pageTextsRef.current;
    if (texts.length === 0) {
      setToast("PDF index not ready yet — try again in a moment.");
      setTimeout(() => setToast(null), 3000);
      return;
    }
    const found = texts.findIndex((t) => tryMatch(t, targetText));
    if (found === -1) {
      setToast("Couldn't locate this row in the PDF.");
      setTimeout(() => setToast(null), 3000);
      return;
    }
    setPage(found + 1);
  }, [targetText, url, pageTextsRef]);

  useEffect(() => {
    if (!targetText) return;
    const id = setTimeout(() => applyHighlight(targetText), 300);
    return () => clearTimeout(id);
  }, [page, targetText, applyHighlight]);

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
      {toast && <div className="pdf-toast">{toast}</div>}
      <div className="pdf-frame">
        <div ref={pageRef}>
          <Document
            file={url}
            onLoadSuccess={(pdf) => setNumPages(pdf.numPages)}
            onLoadError={(err) => console.error("pdf load error", err)}
            loading={<div className="pdf-loading">Loading PDF…</div>}
            error={<div className="pdf-error">Couldn't render PDF preview (this is just visual; extraction still works).</div>}
          >
            <Page
              pageNumber={page}
              scale={scale}
              renderTextLayer
              renderAnnotationLayer={false}
            />
          </Document>
        </div>
      </div>
    </aside>
  );
}
