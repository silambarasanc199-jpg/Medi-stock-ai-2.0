"""FastAPI endpoints for local pharmacy inventory decision support."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app import database, inventory
from app.agent import query_agent
from app.schemas import AgentQuery, BatchInput, ReviewDecision


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize_database()
    yield


app = FastAPI(
    title="MediStock Sentinel AI",
    description="Local-first pharmacy inventory analysis with human-reviewed action drafts.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/api/health")
def health() -> dict:
    ai_configured = bool(os.getenv("AI_API_KEY")) and os.getenv("AI_API_ENABLED", "false").lower() == "true"
    return {"status": "ok", "agent_mode": "llm" if ai_configured else "rule-based", "ai_configured": ai_configured}


@app.get("/api/batches")
def get_batches() -> list[dict]:
    return inventory.list_batches()


@app.post("/api/batches", status_code=status.HTTP_201_CREATED)
def add_batch(body: BatchInput) -> dict:
    try:
        return inventory.create_batch(body.model_dump(), actor="api")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str) -> dict:
    batch = inventory.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Medicine batch not found.")
    return batch


@app.put("/api/batches/{batch_id}")
def edit_batch(batch_id: str, body: BatchInput) -> dict:
    try:
        batch = inventory.update_batch(batch_id, body.model_dump(), actor="api")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not batch:
        raise HTTPException(status_code=404, detail="Medicine batch not found.")
    return batch


@app.delete("/api/batches/{batch_id}")
def remove_batch(batch_id: str) -> dict:
    if not inventory.delete_batch(batch_id, actor="api"):
        raise HTTPException(status_code=404, detail="Medicine batch not found.")
    return {"deleted": True, "batch_id": batch_id, "physical_stock_changed": False}


@app.get("/api/analysis")
def get_analysis() -> dict:
    return inventory.analyze_inventory()


@app.get("/api/drafts")
def get_drafts(status_filter: Literal["pending", "approved", "rejected", "stale"] | None = Query(default=None, alias="status")) -> list[dict]:
    return inventory.list_drafts(status=status_filter)


@app.post("/api/drafts/generate")
def draft_actions() -> dict:
    drafts = inventory.generate_drafts()
    return {"drafts": drafts, "pending_count": sum(draft["status"] == "pending" for draft in drafts), "operations_executed": False}


@app.post("/api/drafts/{draft_id}/review")
def review_action(draft_id: str, body: ReviewDecision) -> dict:
    allowed_roles = {role.strip().lower() for role in os.getenv("AUTHORIZED_REVIEWER_ROLES", "pharmacist,inventory_manager").split(",") if role.strip()}
    if body.reviewer_role.lower() not in allowed_roles:
        raise HTTPException(status_code=403, detail="Reviewer role is not authorized to decide action drafts.")
    try:
        result = inventory.decide_draft(
            draft_id,
            decision=body.decision,
            reviewer_name=body.reviewer_name,
            reviewer_role=body.reviewer_role,
            review_note=body.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Action draft not found.")
    result["action_executed"] = False
    return result


@app.get("/api/impact-report")
def impact_report() -> dict:
    return inventory.impact_report()


@app.get("/api/audit-logs")
def get_audit_logs(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return database.audit_rows(limit=limit)


@app.post("/api/agent/query")
def agent_query(body: AgentQuery) -> dict:
    return query_agent(body.question)
