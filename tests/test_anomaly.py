from dobs.domain.services.anomaly_detector import detect_anomalies
from dobs.domain.value_objects.transaction import Transaction


def _t(date_, amount, side="deposit", **kw):
    return Transaction(
        date=date_,
        description="x",
        deposit=amount if side == "deposit" else None,
        withdrawal=amount if side == "withdrawal" else None,
        confidence=kw.get("confidence"),
    )


async def test_detects_date_out_of_period():
    txns = [
        _t("2025-04-01", 100.0),
        _t("2025-05-15", 200.0),
    ]
    anomalies = await detect_anomalies(txns, "2025-04-01", "2025-04-30")
    assert any(a.kind == "date_out_of_period" and a.transaction_index == 1 for a in anomalies)


async def test_no_anomalies_for_clean_data():
    txns = [_t("2025-04-01", 100.0), _t("2025-04-02", 200.0)]
    anomalies = await detect_anomalies(txns, "2025-04-01", "2025-04-30")
    assert all(a.kind != "date_out_of_period" for a in anomalies)


async def test_detects_duplicate_pair():
    txns = [_t("2025-04-01", 100.0), _t("2025-04-01", 100.0)]
    anomalies = await detect_anomalies(txns, "2025-04-01", "2025-04-30")
    assert any(a.kind == "duplicate_pair" for a in anomalies)


async def test_detects_size_outlier():
    txns = [_t(f"2025-04-{i:02d}", 100.0) for i in range(1, 21)]
    txns.append(_t("2025-04-21", 5_000_000.0))
    anomalies = await detect_anomalies(txns, "2025-04-01", "2025-04-30")
    assert any(a.kind == "size_outlier" for a in anomalies)


async def test_detects_low_confidence():
    t = Transaction(
        date="2025-04-01",
        description="x",
        deposit=100.0,
        confidence=0.3,
    )
    anomalies = await detect_anomalies([t], "2025-04-01", "2025-04-30")
    assert any(a.kind == "low_confidence" for a in anomalies)
