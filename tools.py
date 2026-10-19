"""Constrained tools over persisted inventory; none performs a physical operation."""

from __future__ import annotations

from typing import Any, Callable

from app.inventory import analyze_inventory, generate_drafts, get_draft, list_batches, list_drafts
from app.risk_engine import expiry_risks, reorder_analysis


def get_inventory_status() -> dict[str, Any]:
    return analyze_inventory()


def get_expiry_risk() -> list[dict[str, Any]]:
    return expiry_risks(list_batches())


def forecast_demand(sku: str, days: int) -> dict[str, Any]:
    if not 0 <= days <= 3650:
        raise ValueError("days must be between 0 and 3650")
    matches = [batch for batch in list_batches() if batch["sku"].upper() == sku.upper()]
    if not matches:
        return {"sku": sku.upper(), "found": False, "forecast_units": None}
    daily_usage = max(batch["daily_usage"] for batch in matches)
    return {
        "sku": sku.upper(),
        "found": True,
        "daily_usage_assumption": daily_usage,
        "days": days,
        "forecast_units": round(daily_usage * days, 2),
        "assumption": "Simple average daily use × days; no seasonality or trend adjustment.",
    }


def calculate_reorder(sku: str) -> dict[str, Any]:
    item = next((row for row in reorder_analysis(list_batches()) if row["sku"] == sku.upper()), None)
    return item or {"sku": sku.upper(), "found": False}


def check_transfer_options(sku: str) -> dict[str, Any]:
    exists = any(batch["sku"].upper() == sku.upper() for batch in list_batches())
    return {
        "sku": sku.upper(),
        "inventory_found": exists,
        "transfer_options": [],
        "available": False,
        "reason": "Location-level inventory and transfer permissions are not configured. No transfer was proposed or executed.",
    }


def create_action_draft(sku: str, batch_id: str | None = None) -> dict[str, Any]:
    pending = generate_drafts(actor="agent_tool")
    candidates = [draft for draft in pending if draft["sku"].upper() == sku.upper()]
    if batch_id:
        candidates = [draft for draft in candidates if draft["batch_id"] == batch_id]
    if candidates:
        return {"created_or_pending": True, "drafts": candidates, "message": "Draft only. A human reviewer must decide; no order, transfer, substitution, or stock change was made."}
    return {"created_or_pending": False, "drafts": [], "message": "No current deterministic risk supports a draft for this inventory selection."}


def review_action(action_id: str) -> dict[str, Any]:
    draft = get_draft(action_id)
    if not draft:
        return {"found": False, "action_id": action_id}
    return {
        "found": True,
        "draft": draft,
        "message": "This tool can inspect review status only. A human must use the review endpoint to approve or reject; the agent cannot decide on a person's behalf.",
    }


def get_impact_report() -> dict[str, Any]:
    from app.inventory import impact_report

    return impact_report()


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "get_inventory_status": get_inventory_status,
    "get_expiry_risk": get_expiry_risk,
    "forecast_demand": forecast_demand,
    "calculate_reorder": calculate_reorder,
    "check_transfer_options": check_transfer_options,
    "create_action_draft": create_action_draft,
    "review_action": review_action,
    "get_impact_report": get_impact_report,
}

TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "get_inventory_status", "description": "Return computed inventory metrics and current deterministic expiry/reorder risks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_expiry_risk", "description": "Read FEFO expiry-surplus estimates computed from saved inventory.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "forecast_demand", "description": "Forecast simple demand using saved average daily use.", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}, "days": {"type": "integer", "minimum": 0, "maximum": 3650}}, "required": ["sku", "days"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "calculate_reorder", "description": "Calculate SKU reorder point and suggested quantity from actual saved batches.", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "check_transfer_options", "description": "Check whether location-level transfer options are available. Current MVP has no location map.", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_action_draft", "description": "Create or retrieve only a deterministic, pending human-review draft for a current risk.", "parameters": {"type": "object", "properties": {"sku": {"type": "string"}, "batch_id": {"type": ["string", "null"]}}, "required": ["sku"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "review_action", "description": "Inspect a draft's review state. This tool cannot approve or reject it.", "parameters": {"type": "object", "properties": {"action_id": {"type": "string"}}, "required": ["action_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_impact_report", "description": "Report recorded review decisions and clearly labeled current estimates; never claim unmeasured savings.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
]


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Execute only a registered, schema-constrained inventory tool."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ValueError(f"Tool is not allowed: {name}")
    arguments = arguments or {}
    allowed_arguments = {
        "get_inventory_status": set(), "get_expiry_risk": set(), "forecast_demand": {"sku", "days"},
        "calculate_reorder": {"sku"}, "check_transfer_options": {"sku"},
        "create_action_draft": {"sku", "batch_id"}, "review_action": {"action_id"}, "get_impact_report": set(),
    }[name]
    unexpected = set(arguments) - allowed_arguments
    if unexpected:
        raise ValueError(f"Unexpected tool arguments: {', '.join(sorted(unexpected))}")
    return function(**arguments)
