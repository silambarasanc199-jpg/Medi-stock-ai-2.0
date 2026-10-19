"""Load clearly labeled synthetic data into an empty local database."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from app.database import DB_PATH, audit, connection, initialize_database


def main() -> None:
    initialize_database()
    source = Path(__file__).resolve().parent.parent / "data" / "synthetic_inventory.json"
    dataset = json.loads(source.read_text(encoding="utf-8"))
    with connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        if existing:
            raise SystemExit("The database is not empty. Refusing to mix demo records with existing inventory.")
        for record in dataset["records"]:
            batch_id = str(uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()
            values = dict(record)
            expiry_days = values.pop("expiry_after_days")
            values.update({"id": batch_id, "expiry_date": (date.today() + timedelta(days=expiry_days)).isoformat(), "synthetic": 1, "created_at": timestamp})
            conn.execute(
                """INSERT INTO batches(
                    id, medicine_name, sku, batch_number, expiry_date, quantity, daily_usage,
                    reorder_level, lead_time_days, safety_stock, open_orders, target_stock_days,
                    minimum_order_quantity, unit_cost, synthetic, created_at
                ) VALUES (
                    :id, :medicine_name, :sku, :batch_number, :expiry_date, :quantity, :daily_usage,
                    :reorder_level, :lead_time_days, :safety_stock, :open_orders, :target_stock_days,
                    :minimum_order_quantity, :unit_cost, :synthetic, :created_at
                )""",
                values,
            )
            audit(conn, entity_type="batch", entity_id=batch_id, event="synthetic_seeded", actor="demo_seed", details={"sku": values["sku"], "batch_number": values["batch_number"], "synthetic": True}, created_at=timestamp)
    print(f"Loaded {len(dataset['records'])} synthetic batches into {DB_PATH}")


if __name__ == "__main__":
    main()
