from datetime import date, timedelta

from app.database import audit_rows
from app.tools import execute_tool
from tests.conftest import batch_payload


def add_expiry_batch(client, **overrides):
    payload = batch_payload(
        sku="EXP-500",
        batch_number="EX-EXP",
        expiry_date=(date.today() + timedelta(days=10)).isoformat(),
        quantity=100,
        daily_usage=1,
        reorder_level=0,
        lead_time_days=2,
        safety_stock=0,
        **overrides,
    )
    return client.post("/api/batches", json=payload)


def test_approve_is_a_one_way_human_decision_and_writes_audit(client):
    assert add_expiry_batch(client).status_code == 201
    generated = client.post("/api/drafts/generate").json()
    draft = next(item for item in generated["drafts"] if item["type"] == "expiry_prevention_review")
    result = client.post(
        f"/api/drafts/{draft['id']}/review",
        json={"decision": "approved", "reviewer_name": "Test Pharmacist", "reviewer_role": "pharmacist", "review_note": "Check local transfer rules."},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "approved"
    assert result.json()["action_executed"] is False
    again = client.post(
        f"/api/drafts/{draft['id']}/review",
        json={"decision": "rejected", "reviewer_name": "Test Pharmacist", "reviewer_role": "pharmacist"},
    )
    assert again.status_code == 409
    decision_log = [item for item in audit_rows() if item["entity_id"] == draft["id"] and item["event"] == "approved"]
    assert len(decision_log) == 1
    assert decision_log[0]["details"]["action_executed"] is False


def test_reject_is_recorded_and_unlisted_role_is_forbidden(client):
    add_expiry_batch(client)
    draft = client.post("/api/drafts/generate").json()["drafts"][0]
    forbidden = client.post(f"/api/drafts/{draft['id']}/review", json={"decision": "approved", "reviewer_name": "Someone", "reviewer_role": "guest"})
    assert forbidden.status_code == 403
    rejected = client.post(f"/api/drafts/{draft['id']}/review", json={"decision": "rejected", "reviewer_name": "Inventory Manager", "reviewer_role": "inventory_manager"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    report = client.get("/api/impact-report").json()
    assert report["human_review_decisions_recorded"] == 1
    assert report["measured_waste_prevented"] is None


def test_changed_inventory_marks_old_pending_draft_stale(client):
    created = add_expiry_batch(client).json()
    original = client.post("/api/drafts/generate").json()["drafts"][0]
    replacement_values = batch_payload(
        sku=created["sku"],
        batch_number=created["batch_number"],
        expiry_date=created["expiry_date"],
        quantity=50,
        daily_usage=created["daily_usage"],
        reorder_level=created["reorder_level"],
        lead_time_days=created["lead_time_days"],
        safety_stock=created["safety_stock"],
        unit_cost=created["unit_cost"],
    )
    assert client.put(f"/api/batches/{created['id']}", json=replacement_values).status_code == 200
    current = client.post("/api/drafts/generate").json()["drafts"]
    assert len(current) == 1
    assert current[0]["id"] != original["id"]
    assert client.get("/api/drafts?status=stale").json()[0]["id"] == original["id"]
    attempt = client.post(f"/api/drafts/{original['id']}/review", json={"decision": "approved", "reviewer_name": "Pharmacist", "reviewer_role": "pharmacist"})
    assert attempt.status_code == 409


def test_duplicate_batch_and_invalid_quantities_return_api_errors(client):
    payload = batch_payload(sku="abc-1", batch_number="lot-7")
    assert client.post("/api/batches", json=payload).status_code == 201
    assert client.post("/api/batches", json={**payload, "sku": "ABC-1", "batch_number": "LOT-7"}).status_code == 409
    invalid = client.post("/api/batches", json=batch_payload(sku="OTHER", quantity=-1))
    assert invalid.status_code == 422
    assert client.get("/api/batches/not-a-real-id").status_code == 404


def test_tool_execution_uses_persisted_inventory_and_rejects_unknown_tools(client):
    add_expiry_batch(client)
    status = execute_tool("get_inventory_status")
    assert status["batch_count"] == 1
    forecast = execute_tool("forecast_demand", {"sku": "EXP-500", "days": 10})
    assert forecast["forecast_units"] == 10
    draft_result = execute_tool("create_action_draft", {"sku": "EXP-500"})
    assert draft_result["created_or_pending"] is True
    assert "no order" in draft_result["message"].lower()
    try:
        execute_tool("delete_everything")
    except ValueError as error:
        assert "not allowed" in str(error)
    else:
        raise AssertionError("Unknown tool should not execute")


def test_demo_seed_records_are_explicitly_synthetic(client):
    from app.seed_demo import main as seed_demo

    seed_demo()
    batches = client.get("/api/batches").json()
    assert len(batches) == 4
    assert all(batch["synthetic"] is True for batch in batches)
    assert client.get("/api/impact-report").json()["synthetic_records_included"] is True


def test_missing_ai_configuration_uses_honest_rule_based_fallback(client, monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    from app.agent import query_agent

    add_expiry_batch(client)
    result = query_agent("What should I review?")
    assert result["mode"] == "rule_based"
    assert "estimates" in result["answer"].lower()
    assert "nothing is ordered" in result["answer"].lower()


def test_configured_agent_uses_constrained_tools_and_returns_provider_answer(client, monkeypatch):
    import app.agent as agent

    add_expiry_batch(client)
    monkeypatch.setenv("AI_API_KEY", "test-key-not-used-outside-mock")
    monkeypatch.setenv("AI_API_ENABLED", "true")
    calls = []

    def fake_chat(messages):
        calls.append(messages)
        if len(calls) == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "calculate_reorder", "arguments": '{"sku":"EXP-500"}'}}]}}]}
        assert any(message.get("tool_call_id") == "call-1" for message in messages)
        return {"choices": [{"message": {"role": "assistant", "content": "The saved inventory indicates an expiry review; verify the batch and local policy before acting."}}]}

    monkeypatch.setattr(agent, "_post_chat", fake_chat)
    result = agent.query_agent("What should I review?")
    assert result["mode"] == "llm"
    assert result["answer"].startswith("The saved inventory")
    assert [call["name"] for call in result["tool_calls"]] == ["get_inventory_status", "calculate_reorder"]


def test_review_request_validation_and_unknown_draft(client):
    invalid = client.post("/api/drafts/missing/review", json={"decision": "execute", "reviewer_name": "x", "reviewer_role": "pharmacist"})
    assert invalid.status_code == 422
    missing = client.post("/api/drafts/missing/review", json={"decision": "approved", "reviewer_name": "x", "reviewer_role": "pharmacist"})
    assert missing.status_code == 404
