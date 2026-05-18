from __future__ import annotations

from pathlib import Path

import streamlit as st


def render_file_uploader() -> tuple[list[tuple[bytes, str, bytes | None, str]], bool]:
    col_pdf, col_txt = st.columns([2, 1])
    with col_pdf:
        uploaded_pdfs = st.file_uploader(
            "Statement PDF(s)", type=["pdf"], accept_multiple_files=True
        )
    with col_txt:
        uploaded_txts = st.file_uploader(
            "Pre-OCR'd text file(s) (optional)",
            type=["txt"],
            accept_multiple_files=True,
            help="Match by filename stem (e.g. chase_apr.txt → chase_apr.pdf).",
        )

    use_sample = st.button(":file_folder: Use bundled Ixonia sample", use_container_width=True)

    inputs: list[tuple[bytes, str, bytes | None, str]] = []

    if use_sample:
        root = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
        sample_pdf = root / "Binder2_Redacted.pdf"
        sample_txt = root / "ixonia_ocr.txt"
        if not sample_pdf.exists():
            st.error(f"Sample PDF not found: {sample_pdf}")
            return [], False
        txt_bytes = sample_txt.read_bytes() if sample_txt.exists() else None
        return [(sample_pdf.read_bytes(), "Ixonia (bundled)", txt_bytes, "ixonia_ocr.txt")], True

    if not uploaded_pdfs:
        return [], False

    txt_by_stem: dict[str, tuple[bytes, str]] = {}
    for f in uploaded_txts or []:
        txt_by_stem[Path(f.name).stem] = (f.getvalue(), f.name)

    for f in uploaded_pdfs:
        stem = Path(f.name).stem
        txt_pair = txt_by_stem.get(stem)
        inputs.append(
            (
                f.getvalue(),
                f.name,
                txt_pair[0] if txt_pair else None,
                txt_pair[1] if txt_pair else "",
            )
        )

    return inputs, False
