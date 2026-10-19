"""Validated request and response models for the HTTP API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medicine_name: str = Field(min_length=1, max_length=100)
    sku: str = Field(min_length=1, max_length=40)
    batch_number: str = Field(min_length=1, max_length=40)
    expiry_date: date
    quantity: int = Field(ge=0, le=2_000_000_000)
    daily_usage: float = Field(ge=0, le=1_000_000)
    reorder_level: int = Field(ge=0, le=2_000_000_000)
    lead_time_days: int = Field(ge=0, le=3650)
    safety_stock: int = Field(default=0, ge=0, le=2_000_000_000)
    open_orders: int = Field(default=0, ge=0, le=2_000_000_000)
    target_stock_days: int = Field(default=30, ge=1, le=3650)
    minimum_order_quantity: int | None = Field(default=None, ge=1, le=2_000_000_000)
    unit_cost: float = Field(ge=0, le=1_000_000_000)

    @field_validator("medicine_name", "sku", "batch_number")
    @classmethod
    def strip_and_require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("sku", "batch_number")
    @classmethod
    def normalize_identifiers(cls, value: str) -> str:
        return value.upper()


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reviewer_name: str = Field(min_length=1, max_length=100)
    reviewer_role: str = Field(min_length=1, max_length=60)
    review_note: str | None = Field(default=None, max_length=500)

    @field_validator("reviewer_name", "reviewer_role")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reviewer identity must not be blank")
        return value


class AgentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
