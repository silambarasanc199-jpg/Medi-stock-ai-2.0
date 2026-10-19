"""Optional OpenAI-compatible function-calling agent with a deterministic fallback."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from app.tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """You are MediStock Sentinel, a pharmacy inventory decision-support assistant.
Use the provided live inventory snapshot and the constrained tools for any specific stock claim.
Calculations in tool results are deterministic estimates; do not invent quantities or claim accuracy,
savings, prevented waste, or prevented stockouts. State relevant assumptions and uncertainty.
You may create only a pending action draft when the user explicitly asks for one. Never approve or
reject a draft: review_action is inspection-only, and only a human can decide using the review API.
Never place orders, change physical stock, or recommend a medicine substitution as an action.
Explain that any operational recommendation needs human review and verification against local policy."""


def _ai_enabled() -> bool:
    return bool(os.getenv("AI_API_KEY")) and os.getenv("AI_API_ENABLED", "false").lower() == "true"


def _post_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(
            {
                "model": os.getenv("AI_MODEL", "gpt-4o-mini"),
                "messages": messages,
                "tools": TOOL_DEFINITIONS,
                "tool_choice": "auto",
                "temperature": 0.2,
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['AI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "25"))) as response:
        return json.loads(response.read())


def _rule_based(question: str, *, fallback_reason: str | None = None) -> dict[str, Any]:
    status = execute_tool("get_inventory_status")
    answer = (
        f"Rule-based inventory summary: {status['batch_count']} batches across {status['sku_count']} SKUs; "
        f"{len(status['expiry_risks'])} batch expiry estimate(s) and {len(status['stockout_risks'])} SKU(s) at or below the reorder trigger. "
        f"Estimated expiry cost exposure is ₹{status['expiry_exposure_estimate']:.2f}. These are estimates, "
        "not measured waste or savings. Review any action draft manually; nothing is ordered or changed automatically."
    )
    result = {"mode": "rule_based", "question": question, "answer": answer, "tool_calls": []}
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


def query_agent(question: str) -> dict[str, Any]:
    """Coordinate safe tools when explicitly enabled; otherwise report rule-based results."""
    if not _ai_enabled():
        return _rule_based(question)

    tool_calls: list[dict[str, Any]] = []
    try:
        # Provide an actual, deterministic snapshot even when the model chooses no extra tools.
        snapshot = execute_tool("get_inventory_status")
        snapshot_for_prompt = {
            key: snapshot[key]
            for key in ("as_of", "batch_count", "sku_count", "total_units", "expiry_exposure_estimate", "estimates_only")
        }
        snapshot_for_prompt["expiry_risks"] = snapshot["expiry_risks"][:20]
        snapshot_for_prompt["stockout_risks"] = snapshot["stockout_risks"][:20]
        tool_calls.append({"name": "get_inventory_status", "arguments": {}, "result": snapshot_for_prompt})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Current deterministic tool result (actual saved inventory): " + json.dumps(snapshot_for_prompt)},
            {"role": "user", "content": question},
        ]

        for _ in range(4):
            response = _post_chat(messages)
            choices = response.get("choices") or []
            if not choices:
                raise ValueError("AI provider returned no response choices")
            message = choices[0].get("message") or {}
            calls = message.get("tool_calls") or []
            if not calls:
                answer = message.get("content") or "The AI returned no explanation. Review deterministic analysis in the dashboard."
                return {"mode": "llm", "model": os.getenv("AI_MODEL", "gpt-4o-mini"), "question": question, "answer": answer, "tool_calls": tool_calls, "human_review_required": True}

            messages.append(message)
            for call in calls:
                function = call.get("function", {})
                name = function.get("name", "")
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    outcome = execute_tool(name, arguments)
                    tool_calls.append({"name": name, "arguments": arguments, "result": outcome})
                except Exception as error:
                    outcome = {"error": str(error)}
                    tool_calls.append({"name": name, "arguments": function.get("arguments"), "result": outcome})
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(outcome, default=str)})

        return _rule_based(question, fallback_reason="AI tool-call limit reached; returned deterministic summary instead.")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError) as error:
        reason = "AI service unavailable or returned an invalid response; deterministic fallback used."
        if isinstance(error, TimeoutError):
            reason = "AI request timed out; deterministic fallback used."
        return _rule_based(question, fallback_reason=reason)
