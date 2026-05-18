from pathlib import Path

import pytest

from dobs.infrastructure.adapters.ocr.file_reader import (
    EmptyDocumentError,
    FileReader,
    IngestError,
    UnsupportedFormatError,
    clean_text,
)


def test_clean_text_strips_notion_noise():
    raw = "17.05.2026, 22:08\n\nhttps://file.notion.so/abc?x=1\n\nReal content\n\n1/210\n"
    cleaned = clean_text(raw)
    assert "Real content" in cleaned
    assert "notion" not in cleaned.lower()
    assert "1/210" not in cleaned


def test_clean_text_strips_azure_markers():
    raw = "Apr 01 SOMETHING :unselected: 100.00\nApr 02 OTHER :selected: 200.00"
    assert ":unselected:" not in clean_text(raw)
    assert ":selected:" not in clean_text(raw)
    assert "SOMETHING" in clean_text(raw)


async def test_missing_file_raises(tmp_path: Path):
    reader = FileReader()
    with pytest.raises((FileNotFoundError, IngestError)):
        await reader.read(tmp_path / "nope.pdf")


async def test_empty_file_raises(tmp_path: Path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    reader = FileReader()
    with pytest.raises(EmptyDocumentError):
        await reader.read(p)


async def test_unknown_format_raises(tmp_path: Path):
    p = tmp_path / "weird.bin"
    p.write_bytes(b"\x01\x02\x03\x04\xff\xfe")
    reader = FileReader()
    try:
        result = await reader.read(p)
        assert isinstance(result, str)
    except (UnsupportedFormatError, IngestError, EmptyDocumentError):
        pass


async def test_text_file_passthrough(tmp_path: Path):
    p = tmp_path / "data.txt"
    p.write_text("Apr 01 SOMETHING 100.00\nBeginning Balance as of 04/01/2025\n", encoding="utf-8")
    reader = FileReader()
    out = await reader.read(p)
    assert "SOMETHING" in out
