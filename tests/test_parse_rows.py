from dobs.domain.services.row_parser import RowParser

_parser = RowParser()


def parse_rows(*args, **kwargs):
    return _parser.parse(*args, **kwargs)


def filter_transaction_rows(*args, **kwargs):
    return _parser.filter_transactions(*args, **kwargs)
from dobs.domain.value_objects.raw_row import RawRow


_SAMPLE_FLOWING = (
    "Apr 01 AIRLINEHYD 2759/VENDOR PMT 1,809.28 598,877.98 "
    "Apr 01 METAL TRADERS IN/ACH PAYMEN 9966204593 3,506.80 602,384.78 "
    "Apr 03 PAYABLES 1452496195 10.90 597,069.70 "
    "Apr 15 CHECK #40788 500.00 595,069.70"
)

_SAMPLE_WITH_MARKERS = (
    "Apr 01 BEGINNING BALANCE 597,068.70 "
    "Apr 01 AIRLINEHYD 2759/VENDOR PMT 1,809.28 598,877.98 "
    "Apr 30 ENDING BALANCE 509,121.59"
)


def test_finds_all_rows_in_flowing_text():
    rows = parse_rows(_SAMPLE_FLOWING, "2025-04-01")
    assert len(rows) == 4


def test_iso_date_inferred_from_period():
    rows = parse_rows(_SAMPLE_FLOWING, "2025-04-01")
    assert all(r.date_iso.startswith("2025-04") for r in rows)


def test_amounts_parsed_with_running_balance_split():
    rows = parse_rows(_SAMPLE_FLOWING, "2025-04-01")
    r = rows[0]
    assert list(r.amounts) == [1809.28]
    assert r.balance == 598877.98


def test_check_row_flagged():
    rows = parse_rows(_SAMPLE_FLOWING, "2025-04-01")
    check = [r for r in rows if "CHECK" in r.description]
    assert len(check) == 1
    assert check[0].is_check
    assert list(check[0].amounts) == [500.00]


def test_balance_markers_flagged_and_filtered():
    rows = parse_rows(_SAMPLE_WITH_MARKERS, "2025-04-01")
    assert any(r.likely_marker for r in rows)
    kept = filter_transaction_rows(rows)
    assert all(not r.likely_marker for r in kept)
    assert len(kept) == 1
    assert "AIRLINEHYD" in kept[0].description


def test_filter_drops_empty_description():
    rows = [
        RawRow(date_iso="2025-04-01", description="", amounts=(1.0,),
               balance=None, raw=""),
        RawRow(date_iso="2025-04-01", description="OK", amounts=(1.0,),
               balance=None, raw=""),
    ]
    kept = filter_transaction_rows(rows)
    assert len(kept) == 1


def test_year_rollover_inferred():
    text = "Dec 31 SOMETHING 100.00  500.00  Jan 02 OTHER 200.00 700.00"
    rows = parse_rows(text, "2024-12-15")
    iso = sorted(r.date_iso for r in rows)
    assert iso[0].startswith("2024-12")
    assert iso[1].startswith("2025-01")


def test_negative_balance_supported():
    text = "Sep 03 SOMETHING 50.00 -4.00"
    rows = parse_rows(text, "2024-09-01")
    assert len(rows) == 1
    assert rows[0].balance == -4.00


def test_no_amount_row_skipped():
    text = "Apr 01 NO AMOUNT HERE\nApr 02 GOOD 100.00 1000.00"
    rows = parse_rows(text, "2025-04-01")
    assert len(rows) == 1
    assert "GOOD" in rows[0].description
