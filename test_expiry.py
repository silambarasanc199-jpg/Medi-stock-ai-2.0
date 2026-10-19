from datetime import date, timedelta

from app.risk_engine import expiry_risks


def record(batch_id, batch_number, expiry_days, quantity, daily_usage=4):
    return {
        "id": batch_id,
        "medicine_name": "Synthetic test medicine",
        "sku": "TEST-1",
        "batch_number": batch_number,
        "expiry_date": (date(2026, 1, 1) + timedelta(days=expiry_days)).isoformat(),
        "quantity": quantity,
        "daily_usage": daily_usage,
        "unit_cost": 0.25,
    }


def test_fefo_demand_is_allocated_once_across_batches():
    risks = expiry_risks(
        [record("early", "EARLY", 10, 80), record("later", "LATER", 30, 60)],
        as_of=date(2026, 1, 1),
    )
    assert [(risk["batch_id"], risk["potential_surplus"]) for risk in risks] == [("early", 40)]
    assert risks[0]["estimated_exposure"] == 10.0


def test_same_expiry_batches_share_one_demand_forecast():
    risks = expiry_risks(
        [record("a", "A", 10, 30), record("b", "B", 10, 50)],
        as_of=date(2026, 1, 1),
    )
    assert sum(risk["potential_surplus"] for risk in risks) == 40


def test_expired_batch_is_flagged_as_full_quantity_without_future_demand():
    risks = expiry_risks([record("expired", "OLD", -2, 17)], as_of=date(2026, 1, 1))
    assert len(risks) == 1
    assert risks[0]["status"] == "expired"
    assert risks[0]["potential_surplus"] == 17
    assert risks[0]["expected_demand_through_expiry"] == 0


def test_batch_outside_horizon_is_not_reported():
    risks = expiry_risks([record("future", "FUTURE", 120, 30)], as_of=date(2026, 1, 1))
    assert risks == []
