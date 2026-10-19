"""Small SQLite persistence layer with explicit audit history."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("MEDISTOCK_DB_PATH", ROOT / "data" / "medistock.sqlite3"))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                medicine_name TEXT NOT NULL,
                sku TEXT NOT NULL,
                batch_number TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                daily_usage REAL NOT NULL CHECK (daily_usage >= 0),
                reorder_level INTEGER NOT NULL CHECK (reorder_level >= 0),
                lead_time_days INTEGER NOT NULL CHECK (lead_time_days >= 0),
                safety_stock INTEGER NOT NULL DEFAULT 0 CHECK (safety_stock >= 0),
                open_orders INTEGER NOT NULL DEFAULT 0 CHECK (open_orders >= 0),
                target_stock_days INTEGER NOT NULL DEFAULT 30 CHECK (target_stock_days >= 1),
                minimum_order_quantity INTEGER CHECK (minimum_order_quantity IS NULL OR minimum_order_quantity >= 1),
                unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
                synthetic INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_batches_sku_batch
                ON batches(UPPER(sku), UPPER(batch_number));
            CREATE INDEX IF NOT EXISTS ix_batches_sku ON batches(sku);
            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                sku TEXT NOT NULL,
                batch_id TEXT,
                title TEXT NOT NULL,
                explanation TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'stale')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewer TEXT,
                reviewer_role TEXT,
                review_note TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_drafts_status ON drafts(status);
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event TEXT NOT NULL,
                actor TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_logs(entity_type, entity_id);
            """
        )


def audit(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: str,
    event: str,
    actor: str,
    details: dict[str, Any],
    created_at: str,
) -> None:
    conn.execute(
        """INSERT INTO audit_logs(entity_type, entity_id, event, actor, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, event, actor, json.dumps(details, sort_keys=True), created_at),
    )


def audit_rows(limit: int = 100) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {**dict(row), "details": json.loads(row["details_json"])} for row in rows
    ]
