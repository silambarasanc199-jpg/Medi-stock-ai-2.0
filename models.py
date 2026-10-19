"""Domain records returned by SQLite services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MedicineBatch:
    id: str
    medicine_name: str
    sku: str
    batch_number: str
    expiry_date: str
    quantity: int
    daily_usage: float
    reorder_level: int
    lead_time_days: int
    safety_stock: int
    open_orders: int
    target_stock_days: int
    minimum_order_quantity: int | None
    unit_cost: float
    synthetic: bool
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "MedicineBatch":
        values = dict(row)
        values["synthetic"] = bool(values["synthetic"])
        return cls(**values)

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__}


def draft_from_row(row: Any) -> dict[str, Any]:
    draft = dict(row)
    draft["evidence"] = json.loads(draft.pop("evidence_json"))
    return draft
