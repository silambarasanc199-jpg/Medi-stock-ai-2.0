from datetime import date, timedelta

from app.risk_engine import reorder_analysis, stockout_risks


def stock(quantity, *, open_orders=0, daily=5, lead=4, safety=10, manual=22, moq=110):
    return {
        "id": "stock-1",
        "medicine_name": "Synthetic test medicine",
        "sku": "TEST-2",
        "batch_number": "ST-001",
        "expiry_date": (date(2026, 1, 1) + timedelta(days=200)).isoformat(),
        "quantity": quantity,
        "daily_usage": daily,
        "reorder_level": manual,
        "lead_time_days": lead,
        "safety_stock": safety,
        "open_orders": open_orders,
        "target_stock_days": 20,
        "minimum_order_quantity": moq,
        "unit_cost": 1.0,
    }


def test_reorder_point_formula_order_position_and_supplier_minimum():
    result = reorder_analysis([stock(26, open_orders=2)], as_of=date(2026, 1, 1))[0]
    assert result["calculated_reorder_point"] == 30  # 5 daily × 4 lead + 10 safety
    assert result["inventory_position"] == 28
    assert result["at_or_below_trigger"] is True
    assert result["quantity_before_moq"] == 102
    assert result["suggested_order_quantity"] == 110


def test_open_orders_can_raise_inventory_position_above_trigger():
    assert stockout_risks([stock(26, open_orders=5)], as_of=date(2026, 1, 1)) == []


def test_expired_stock_is_not_counted_as_usable_for_reorder():
    item = stock(100, open_orders=0)
    item["expiry_date"] = "2025-12-31"
    result = reorder_analysis([item], as_of=date(2026, 1, 1))[0]
    assert result["on_hand"] == 0
    assert result["at_or_below_trigger"] is True


def test_no_supplier_minimum_uses_calculated_quantity():
    item = stock(26, open_orders=2, moq=None)
    result = reorder_analysis([item], as_of=date(2026, 1, 1))[0]
    assert result["suggested_order_quantity"] == 102
