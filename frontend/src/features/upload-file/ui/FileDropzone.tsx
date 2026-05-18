import { useCallback, useState } from "react";

interface Props {
  pdf: File | null;
  setPdf: (f: File | null) => void;
  txt: File | null;
  setTxt: (f: File | null) => void;
  onRun: () => void;
  canRun: boolean;
  running: boolean;
}

export function FileDropzone(p: Props) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      for (const f of files) {
        if (f.name.toLowerCase().endsWith(".pdf")) p.setPdf(f);
        else if (f.name.toLowerCase().endsWith(".txt")) p.setTxt(f);
      }
    },
    [p],
  );

  return (
    <div
      className={`dropzone ${dragOver ? "dragover" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <div className="dropzone-content">
        <div className="dropzone-prompt">
          Drag &amp; drop a <strong>PDF</strong> (and optional <strong>.txt</strong>)
          here, or click to browse.
        </div>

        <div className="file-pickers">
          <label className="file-picker">
            <span>PDF</span>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => p.setPdf(e.target.files?.[0] ?? null)}
            />
            <span className="file-name">
              {p.pdf ? p.pdf.name : "no file"}
            </span>
          </label>

          <label className="file-picker">
            <span>OCR text (optional)</span>
            <input
              type="file"
              accept=".txt"
              onChange={(e) => p.setTxt(e.target.files?.[0] ?? null)}
            />
            <span className="file-name">
              {p.txt ? p.txt.name : "no file"}
            </span>
          </label>
        </div>

        <button
          className="run-btn"
          onClick={p.onRun}
          disabled={!p.canRun}
        >
          {p.running ? "Running..." : "Extract"}
        </button>
      </div>
    </div>
  );
}
