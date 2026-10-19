from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.sqlite3")
    database.initialize_database()
    with TestClient(app) as test_client:
        yield test_client


def batch_payload(**overrides):
    values = {
        "medicine_name": "Example medicine 250 mg",
        "sku": "EX-250",
        "batch_number": "EX-001",
        "expiry_date": (date.today() + timedelta(days=180)).isoformat(),
        "quantity": 100,
        "daily_usage": 2,
        "reorder_level": 20,
        "lead_time_days": 5,
        "safety_stock": 10,
        "open_orders": 0,
        "target_stock_days": 30,
        "minimum_order_quantity": None,
        "unit_cost": 0.5,
    }
    return {**values, **overrides}
