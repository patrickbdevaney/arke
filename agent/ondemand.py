"""
agent/ondemand.py — on-demand forecast request queue.

The paid MCP tool `request_forecast(condition_id)` enqueues a council run for an
arbitrary Polymarket market and returns a job id. A worker (the scheduler, a
follow-up) drains the queue out of band and runs the council; for this pass the
table + enqueue is enough to hand callers a real, pollable job id.

Storage is a small SQLite table in the SAME database file as the rest of Arke
(ARKE_DB_PATH or the default arke.db) created lazily and idempotently, so it
never touches or migrates the existing schema destructively — it only ever adds
its own `ondemand_jobs` table.

Rate limit: at most MAX_QUEUED_PER_HOUR (10) jobs may be enqueued per rolling
hour; past the cap, enqueue returns a friendly error instead of a job id. Fails
open in the sense of never crashing the MCP server — on any DB error it returns
a structured error dict.
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Same default DB location as agent/db.py (repo root / arke.db).
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "arke.db"

MAX_QUEUED_PER_HOUR = 10
ETA_SECONDS = 90


def _db_path() -> str:
    return os.getenv("ARKE_DB_PATH") or str(_DEFAULT_DB)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create the ondemand_jobs table if it doesn't exist. Idempotent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ondemand_jobs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'queued',
            created_at   TEXT    NOT NULL,
            created_at_ts INTEGER NOT NULL DEFAULT 0,
            result_cid   TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ondemand_created "
        "ON ondemand_jobs(created_at_ts DESC)"
    )


def _now():
    dt = datetime.now(timezone.utc)
    return dt.isoformat(), int(dt.timestamp())


def enqueue_forecast(condition_id: str) -> dict:
    """Enqueue an on-demand council run for `condition_id`.

    Returns {"job_id", "status": "queued", "eta_seconds"} on success, or a
    structured {"error": ...} dict when the rate limit is hit, the id is empty,
    or the DB is unavailable. Never raises."""
    if not condition_id:
        return {"error": "condition_id required"}
    try:
        created_at, created_ts = _now()
        with _conn() as conn:
            _ensure_table(conn)
            cutoff = created_ts - 3600
            recent = conn.execute(
                "SELECT COUNT(*) FROM ondemand_jobs WHERE created_at_ts > ?",
                (cutoff,),
            ).fetchone()[0]
            if recent >= MAX_QUEUED_PER_HOUR:
                return {
                    "error": "rate_limited",
                    "message": (
                        f"on-demand forecast queue is at its cap of "
                        f"{MAX_QUEUED_PER_HOUR}/hour — try again later"
                    ),
                    "retry_after_seconds": 3600,
                }
            cur = conn.execute(
                "INSERT INTO ondemand_jobs "
                "(condition_id, status, created_at, created_at_ts) "
                "VALUES (?, 'queued', ?, ?)",
                (condition_id, created_at, created_ts),
            )
            job_id = cur.lastrowid
        return {"job_id": job_id, "status": "queued", "eta_seconds": ETA_SECONDS}
    except Exception as e:
        log.warning("[ondemand] enqueue failed: %s", e)
        return {"error": "temporarily unavailable"}


def get_job(job_id: int) -> dict | None:
    """Read a queued job's status. Returns None if not found. Never raises."""
    try:
        with _conn() as conn:
            _ensure_table(conn)
            row = conn.execute(
                "SELECT id, condition_id, status, created_at, result_cid "
                "FROM ondemand_jobs WHERE id = ?",
                (int(job_id),),
            ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        log.warning("[ondemand] get_job failed: %s", e)
        return None
