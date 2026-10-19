"""Inventory and review services shared by the API and agent tools."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from app.database import audit, connection
from app.models import MedicineBatch, draft_from_row
from app.risk_engine import expiry_risks, reorder_analysis, stockout_risks


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_batches() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM batches ORDER BY expiry_date, sku, batch_number").fetchall()
    return [MedicineBatch.from_row(row).as_dict() for row in rows]


def get_batch(batch_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    return MedicineBatch.from_row(row).as_dict() if row else None


def create_batch(values: dict[str, Any], *, actor: str = "api") -> dict[str, Any]:
    created_at = now_utc()
    batch_id = str(uuid4())
    batch = {**values, "id": batch_id, "synthetic": False, "created_at": created_at}
    batch["expiry_date"] = str(batch["expiry_date"])
    try:
        with connection() as conn:
            conn.execute(
                """INSERT INTO batches(
                    id, medicine_name, sku, batch_number, expiry_date, quantity, daily_usage,
                    reorder_level, lead_time_days, safety_stock, open_orders, target_stock_days,
                    minimum_order_quantity, unit_cost, synthetic, created_at
                ) VALUES (
                    :id, :medicine_name, :sku, :batch_number, :expiry_date, :quantity, :daily_usage,
                    :reorder_level, :lead_time_days, :safety_stock, :open_orders, :target_stock_days,
                    :minimum_order_quantity, :unit_cost, 0, :created_at
                )""",
                batch,
            )
            audit(conn, entity_type="batch", entity_id=batch_id, event="created", actor=actor, details={"sku": batch["sku"], "batch_number": batch["batch_number"]}, created_at=created_at)
    except sqlite3.IntegrityError as exc:
        if "uq_batches_sku_batch" in str(exc) or "batches.sku" in str(exc):
            raise ValueError("A batch with this SKU and batch number already exists.") from exc
        raise
    return get_batch(batch_id)  # type: ignore[return-value]


def update_batch(batch_id: str, values: dict[str, Any], *, actor: str = "api") -> dict[str, Any] | None:
    created_at = now_utc()
    updated = {**values, "expiry_date": str(values["expiry_date"]), "id": batch_id}
    columns = [
        "medicine_name", "sku", "batch_number", "expiry_date", "quantity", "daily_usage",
        "reorder_level", "lead_time_days", "safety_stock", "open_orders", "target_stock_days",
        "minimum_order_quantity", "unit_cost",
    ]
    try:
        with connection() as conn:
            cursor = conn.execute(
                "UPDATE batches SET " + ", ".join(f"{column} = :{column}" for column in columns) + " WHERE id = :id",
                updated,
            )
            if cursor.rowcount == 0:
                return None
            audit(conn, entity_type="batch", entity_id=batch_id, event="updated", actor=actor, details={"sku": updated["sku"], "batch_number": updated["batch_number"]}, created_at=created_at)
    except sqlite3.IntegrityError as exc:
        raise ValueError("A batch with this SKU and batch number already exists.") from exc
    return get_batch(batch_id)


def delete_batch(batch_id: str, *, actor: str = "api") -> bool:
    with connection() as conn:
        row = conn.execute("SELECT sku, batch_number FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            return False
        audit(conn, entity_type="batch", entity_id=batch_id, event="deleted", actor=actor, details=dict(row), created_at=now_utc())
        conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
    return True


def analyze_inventory(*, as_of: date | None = None) -> dict[str, Any]:
    batches = list_batches()
    expiry = expiry_risks(batches, as_of=as_of)
    reorder = reorder_analysis(batches, as_of=as_of)
    stockout = [item for item in reorder if item["at_or_below_trigger"]]
    return {
        "as_of": (as_of or date.today()).isoformat(),
        "batch_count": len(batches),
        "sku_count": len({batch["sku"].upper() for batch in batches}),
        "total_units": sum(batch["quantity"] for batch in batches),
        "expiry_exposure_estimate": round(sum(item["estimated_exposure"] for item in expiry), 2),
        "expiry_risks": expiry,
        "reorder_analysis": reorder,
        "stockout_risks": stockout,
        "estimates_only": True,
    }


def list_drafts(status: str | None = None) -> list[dict[str, Any]]:
    with connection() as conn:
        if status:
            rows = conn.execute("SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM drafts ORDER BY created_at DESC").fetchall()
    return [draft_from_row(row) for row in rows]


def get_draft(draft_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return draft_from_row(row) if row else None


def generate_drafts(*, actor: str = "rule_engine") -> list[dict[str, Any]]:
    analysis = analyze_inventory()
    timestamp = now_utc()
    batches = {batch["id"]: batch for batch in list_batches()}
    candidates: list[dict[str, Any]] = []
    for risk in analysis["expiry_risks"]:
        batch = batches[risk["batch_id"]]
        source_key = json.dumps(
            ["expiry", batch["id"], batch["quantity"], batch["daily_usage"], batch["unit_cost"], batch["expiry_date"]],
            separators=(",", ":"),
        )
        expired = risk["status"] == "expired"
        title = f"{'Quarantine' if expired else 'Expiry plan'} review: {batch['medicine_name']}"
        explanation = (
            f"This batch passed its recorded expiry date. {risk['potential_surplus']} units are excluded from usable stock; estimated cost exposure is ₹{risk['estimated_exposure']:.2f}. Confirm local quarantine and disposal policy."
            if expired
            else f"{risk['potential_surplus']} units may remain when this batch expires in {risk['days_until_expiry']} days. Forecast demand is allocated FEFO across batches to avoid double-counting. Verify actual sales and local policy before considering a transfer or other action. Estimated cost exposure is ₹{risk['estimated_exposure']:.2f}, not a measured loss."
        )
        evidence = [f"Batch {batch['batch_number']} · expiry {batch['expiry_date']}", f"{batch['quantity']} on hand · {risk['potential_surplus']} estimated surplus", f"{risk['daily_usage']} units/day · {risk['days_until_expiry']} days to expiry", f"Estimated exposure ${risk['estimated_exposure']:.2f}"]
        candidates.append({"source_key": source_key, "type": "expired_stock_review" if expired else "expiry_prevention_review", "sku": risk["sku"], "batch_id": batch["id"], "title": title, "explanation": explanation, "evidence": evidence})
    for risk in analysis["stockout_risks"]:
        source_key = json.dumps(
            ["reorder", risk["sku"], risk["on_hand"], risk["open_orders"], risk["daily_usage"], risk["lead_time_days"], risk["safety_stock"], risk["manual_reorder_level"], risk["target_days"], risk["minimum_order_quantity"]],
            separators=(",", ":"),
        )
        explanation = (
            f"Inventory position {risk['inventory_position']} units ({risk['on_hand']} on hand + {risk['open_orders']} open orders). Formula reorder point = {risk['daily_usage']} × {risk['lead_time_days']} + {risk['safety_stock']} = {risk['calculated_reorder_point']}; manual level {risk['manual_reorder_level']} gives effective trigger {risk['trigger']}. Suggested quantity {risk['suggested_order_quantity']} targets {risk['target_stock']} units of coverage"
            + (f" and respects the {risk['minimum_order_quantity']}-unit supplier minimum" if risk["minimum_order_quantity"] else "")
            + ". Verify open orders, supplier availability, demand, and policy before placing any order. No order is placed by this draft."
        )
        evidence = [f"{risk['on_hand']} on hand + {risk['open_orders']} on order", f"Formula reorder point {risk['calculated_reorder_point']}", f"{risk['daily_usage']} daily use · {risk['lead_time_days']}-day lead · {risk['safety_stock']} safety stock", f"{risk['suggested_order_quantity']} units suggested · estimate only"]
        candidates.append({"source_key": source_key, "type": "replenishment_review", "sku": risk["sku"], "batch_id": None, "title": f"Replenishment review: {risk['medicine_name']}", "explanation": explanation, "evidence": evidence})

    current_keys = {item["source_key"] for item in candidates}
    with connection() as conn:
        existing_rows = {row["source_key"]: row for row in conn.execute("SELECT * FROM drafts").fetchall()}
        for source_key, row in existing_rows.items():
            if row["status"] == "pending" and source_key not in current_keys:
                note = "Inventory changed or the deterministic risk no longer applies; generate current drafts before deciding."
                conn.execute("UPDATE drafts SET status = 'stale', reviewed_at = ?, reviewer = 'system', reviewer_role = 'system', review_note = ? WHERE id = ?", (timestamp, note, row["id"]))
                audit(conn, entity_type="draft", entity_id=row["id"], event="superseded", actor=actor, details={"status": "stale", "source_key": source_key}, created_at=timestamp)

        for candidate in candidates:
            previous = existing_rows.get(candidate["source_key"])
            if previous and previous["status"] in ("approved", "rejected"):
                continue
            if previous and previous["status"] == "pending":
                evidence_json = json.dumps(candidate["evidence"])
                if previous["title"] != candidate["title"] or previous["explanation"] != candidate["explanation"] or previous["evidence_json"] != evidence_json:
                    conn.execute("UPDATE drafts SET title = ?, explanation = ?, evidence_json = ? WHERE id = ?", (candidate["title"], candidate["explanation"], evidence_json, previous["id"]))
                    audit(conn, entity_type="draft", entity_id=previous["id"], event="refreshed", actor=actor, details={"status": "pending", "source_key": candidate["source_key"]}, created_at=timestamp)
                continue
            if previous and previous["status"] == "stale":
                conn.execute("UPDATE drafts SET status = 'pending', title = ?, explanation = ?, evidence_json = ?, created_at = ?, reviewed_at = NULL, reviewer = NULL, reviewer_role = NULL, review_note = NULL WHERE id = ?", (candidate["title"], candidate["explanation"], json.dumps(candidate["evidence"]), timestamp, previous["id"]))
                audit(conn, entity_type="draft", entity_id=previous["id"], event="reactivated", actor=actor, details={"status": "pending", "source_key": candidate["source_key"]}, created_at=timestamp)
                continue
            _insert_draft(conn, **candidate, timestamp=timestamp, actor=actor)
    return list_drafts(status="pending")


def _insert_draft(conn: sqlite3.Connection, *, source_key: str, type: str, sku: str, batch_id: str | None, title: str, explanation: str, evidence: list[str], timestamp: str, actor: str) -> str:
    draft_id = str(uuid4())
    conn.execute(
        """INSERT INTO drafts(id, source_key, type, sku, batch_id, title, explanation, evidence_json, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (draft_id, source_key, type, sku, batch_id, title, explanation, json.dumps(evidence), timestamp),
    )
    audit(conn, entity_type="draft", entity_id=draft_id, event="created", actor=actor, details={"type": type, "sku": sku, "status": "pending"}, created_at=timestamp)
    return draft_id


def decide_draft(draft_id: str, *, decision: str, reviewer_name: str, reviewer_role: str, review_note: str | None) -> dict[str, Any] | None:
    timestamp = now_utc()
    with connection() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            return None
        if row["status"] != "pending":
            raise ValueError(f"Draft is already {row['status']} and cannot be reviewed again.")
        conn.execute(
            "UPDATE drafts SET status = ?, reviewed_at = ?, reviewer = ?, reviewer_role = ?, review_note = ? WHERE id = ? AND status = 'pending'",
            (decision, timestamp, reviewer_name, reviewer_role, review_note, draft_id),
        )
        audit(conn, entity_type="draft", entity_id=draft_id, event=decision, actor=reviewer_name, details={"role": reviewer_role, "review_note": review_note, "status": decision, "action_executed": False}, created_at=timestamp)
    return get_draft(draft_id)


def impact_report() -> dict[str, Any]:
    analysis = analyze_inventory()
    with connection() as conn:
        counts = {row["status"]: row["count"] for row in conn.execute("SELECT status, COUNT(*) AS count FROM drafts GROUP BY status").fetchall()}
        decision_count = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_type = 'draft' AND event IN ('approved', 'rejected')").fetchone()[0]
    return {
        "as_of": analysis["as_of"],
        "synthetic_records_included": any(batch["synthetic"] for batch in list_batches()),
        "estimated_expiry_cost_exposure": analysis["expiry_exposure_estimate"],
        "expiry_surplus_units_estimated": sum(item["potential_surplus"] for item in analysis["expiry_risks"]),
        "stockout_skus_at_trigger": len(analysis["stockout_risks"]),
        "human_review_decisions_recorded": decision_count,
        "draft_status_counts": {key: counts.get(key, 0) for key in ("pending", "approved", "rejected", "stale")},
        "measured_waste_prevented": None,
        "measured_stockouts_prevented": None,
        "note": "Exposure and surplus are current estimates, not measured savings. Approval is logged only; completed operational actions and their outcomes must be recorded separately to measure impact.",
    }
