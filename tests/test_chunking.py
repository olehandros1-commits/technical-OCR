from datetime import date
from dobs.application.services.chunking import TransactionChunker

_chunker = TransactionChunker()


def chunk_segment_by_date_ranges(*args, **kwargs):
    return _chunker.chunk_by_date_ranges(*args, **kwargs)


def merge_chunks(*args, **kwargs):
    return _chunker.merge(*args, **kwargs)
from dobs.domain.value_objects.transaction import Transaction


def _make_segment(n_days: int = 20) -> str:
    """Build a fake segment with one date-line per day."""
    lines = [
        "Ixonia Bank",
        "Account Number: 4664",
        "Beginning Balance as of 04/01/2025 $1000.00",
    ]
    for day in range(1, n_days + 1):
        lines.append(f"Apr {day:02d}   SOMETHING {day*10:.2f}   {1000+day*10:.2f}")
    lines.append("DAILY BALANCE SUMMARY")
    lines.append("Apr 01 $1010.00")
    return "\n".join(lines)


def test_small_segment_returns_single_chunk():
    text = _make_segment(n_days=5)
    chunks = chunk_segment_by_date_ranges(
        text, "2025-04-01", "2025-04-30",
        n_chunks=4, min_transactions_to_chunk=80,
    )
    assert len(chunks) == 1


def test_large_segment_is_split():
    # 100 date-lines triggers chunking at default threshold (80).
    text = _make_segment(n_days=100)
    text = text.replace("Apr 30", "Apr 30")  # ensure parser works on 30+
    # Switch to a month-based sweep so dates stay valid.
    lines = [
        "Ixonia Bank",
        "Account Number: 4664",
        "Beginning Balance as of 04/01/2025 $1000.00",
    ]
    for i in range(100):
        d = 1 + (i % 28)
        lines.append(f"Apr {d:02d}   ROW{i} {(i+1)*1.5:.2f}   {2000+i:.2f}")
    text2 = "\n".join(lines)
    chunks = chunk_segment_by_date_ranges(
        text2, "2025-04-01", "2025-04-30",
        n_chunks=4, min_transactions_to_chunk=80,
    )
    assert len(chunks) > 1
    # Each chunk has the header (bank line) preserved.
    for c in chunks:
        assert "Ixonia Bank" in c.text


def test_chunk_hint_mentions_range():
    text = "\n".join(
        ["Ixonia Bank", "Account 4664"]
        + [f"Apr {d:02d}   X {d}.00   {d}.00" for d in range(1, 29)] * 4
    )
    chunks = chunk_segment_by_date_ranges(
        text, "2025-04-01", "2025-04-30",
        n_chunks=3, min_transactions_to_chunk=10,
    )
    assert len(chunks) >= 2
    hint = chunks[0].hint()
    assert "2025-04-" in hint
    assert "chunk 1 of" in hint


def test_merge_chunks_dedupes_overlap():
    t1 = [Transaction(date="2025-04-01", description="A", deposit=100.0)]
    t2 = [
        Transaction(date="2025-04-01", description="A", deposit=100.0),  # dup
        Transaction(date="2025-04-02", description="B", deposit=200.0),
    ]
    merged = merge_chunks([t1, t2])
    assert len(merged) == 2
    assert merged[0].description == "A"
    assert merged[1].description == "B"
