"""Deterministic pharmacy stock risk calculations; no model-generated arithmetic."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any, Iterable


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def expiry_risks(
    batches: Iterable[dict[str, Any]],
    *,
    as_of: date | None = None,
    horizon_days: int = 90,
) -> list[dict[str, Any]]:
    """Estimate surplus at expiry using FEFO allocation within each SKU."""
    today = as_of or date.today()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for batch in batches:
        groups[str(batch["sku"]).upper()].append(batch)

    results = []
    for sku, records in groups.items():
        daily_usage = max((float(batch["daily_usage"]) for batch in records), default=0.0)
        earlier_demand_allocated = 0.0
        for batch in sorted(records, key=lambda item: _date(item["expiry_date"])):
            expiry = _date(batch["expiry_date"])
            days = (expiry - today).days
            expected_demand = daily_usage * max(days, 0)
            prior_demand_allocated = earlier_demand_allocated
            demand_remaining = max(0.0, expected_demand - prior_demand_allocated)
            quantity = int(batch["quantity"])
            surplus = quantity if days < 0 else max(0.0, quantity - min(quantity, demand_remaining))
            if 0 <= days <= horizon_days:
                earlier_demand_allocated += min(quantity, demand_remaining)
            if days <= horizon_days and surplus > 0:
                results.append(
                    {
                        "sku": sku,
                        "batch_id": batch["id"],
                        "medicine_name": batch["medicine_name"],
                        "batch_number": batch["batch_number"],
                        "expiry_date": expiry.isoformat(),
                        "days_until_expiry": days,
                        "quantity": quantity,
                        "daily_usage": daily_usage,
                        "expected_demand_through_expiry": round(expected_demand, 2),
                        "prior_demand_allocated": round(prior_demand_allocated, 2),
                        "potential_surplus": int(math.ceil(surplus)),
                        "unit_cost": float(batch["unit_cost"]),
                        "estimated_exposure": round(math.ceil(surplus) * float(batch["unit_cost"]), 2),
                        "status": "expired" if days < 0 else "near_expiry",
                        "assumption": "SKU-level daily use is the highest recorded batch value; demand is allocated once in first-expiry-first-out order.",
                    }
                )
    return sorted(results, key=lambda risk: (risk["days_until_expiry"], risk["sku"], risk["batch_id"]))


def reorder_analysis(
    batches: Iterable[dict[str, Any]], *, as_of: date | None = None
) -> list[dict[str, Any]]:
    """Calculate position, formula reorder point, and an MOQ-aware order estimate."""
    today = as_of or date.today()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for batch in batches:
        groups[str(batch["sku"]).upper()].append(batch)

    results = []
    for sku, records in groups.items():
        usable = [batch for batch in records if _date(batch["expiry_date"]) >= today]
        daily_usage = max((float(batch["daily_usage"]) for batch in records), default=0.0)
        lead_time = max((int(batch["lead_time_days"]) for batch in records), default=0)
        safety_stock = max((int(batch.get("safety_stock", 0)) for batch in records), default=0)
        manual_level = max((int(batch["reorder_level"]) for batch in records), default=0)
        on_hand = sum(int(batch["quantity"]) for batch in usable)
        open_orders = sum(int(batch.get("open_orders", 0)) for batch in usable)
        position = on_hand + open_orders
        calculated_point = daily_usage * lead_time + safety_stock
        trigger = max(calculated_point, manual_level)
        target_days = max((int(batch.get("target_stock_days", 30)) for batch in records), default=30)
        target_stock = max(trigger, daily_usage * (lead_time + target_days) + safety_stock)
        quantity_before_moq = max(0, math.ceil(target_stock - position))
        minimum_order = max(
            (int(batch["minimum_order_quantity"] or 0) for batch in records), default=0
        )
        suggested = (
            max(quantity_before_moq, minimum_order) if quantity_before_moq and minimum_order else quantity_before_moq
        )
        days_of_stock = on_hand / daily_usage if daily_usage > 0 else None
        results.append(
            {
                "sku": sku,
                "medicine_name": records[0]["medicine_name"],
                "daily_usage": daily_usage,
                "lead_time_days": lead_time,
                "safety_stock": safety_stock,
                "on_hand": on_hand,
                "open_orders": open_orders,
                "inventory_position": position,
                "calculated_reorder_point": round(calculated_point, 2),
                "manual_reorder_level": manual_level,
                "trigger": round(trigger, 2),
                "target_days": target_days,
                "target_stock": round(target_stock, 2),
                "quantity_before_moq": quantity_before_moq,
                "minimum_order_quantity": minimum_order or None,
                "suggested_order_quantity": suggested,
                "days_of_stock": round(days_of_stock, 2) if days_of_stock is not None else None,
                "at_or_below_trigger": position <= trigger,
                "batch_ids": [batch["id"] for batch in usable],
                "assumption": "Usable stock excludes expired batches. SKU demand is the highest recorded daily-use value; open orders and supplier minimums are taken from entered records.",
            }
        )
    return sorted(results, key=lambda item: (item["days_of_stock"] is None, item["days_of_stock"] or 0))


def stockout_risks(
    batches: Iterable[dict[str, Any]], *, as_of: date | None = None
) -> list[dict[str, Any]]:
    return [item for item in reorder_analysis(batches, as_of=as_of) if item["at_or_below_trigger"]]
