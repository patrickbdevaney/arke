"""
db.py — Arke persistence layer

Tracks every market Arke has processed to prevent duplicate posts.
Single SQLite file, zero dependencies beyond stdlib.

Usage:
    from agent.db import ArkeDB
    db = ArkeDB()
    if not db.already_posted(condition_id):
        db.record_post(market)
"""

import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "arke.db"


class ArkeDB:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS posted_markets (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id        TEXT NOT NULL UNIQUE,
                    question            TEXT NOT NULL,
                    slug                TEXT NOT NULL,
                    event_slug          TEXT,
                    market_url          TEXT NOT NULL,
                    probability_pct     INTEGER NOT NULL,
                    volume_24hr         REAL NOT NULL,
                    end_date            TEXT,
                    tweet_text          TEXT NOT NULL,
                    opentweet_post_id   TEXT,
                    x_post_url          TEXT,
                    posted_at           TEXT NOT NULL,
                    resolved            INTEGER NOT NULL DEFAULT 0,
                    resolution          TEXT,
                    was_correct         INTEGER
                );

                CREATE TABLE IF NOT EXISTS feed_snapshots (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapped_at          TEXT NOT NULL,
                    market_count        INTEGER NOT NULL,
                    top_market_question TEXT,
                    top_market_volume   REAL
                );

                CREATE TABLE IF NOT EXISTS skipped_markets (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id        TEXT NOT NULL,
                    question            TEXT NOT NULL,
                    reason              TEXT NOT NULL,
                    skipped_at          TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_posted_condition
                    ON posted_markets(condition_id);

                CREATE INDEX IF NOT EXISTS idx_posted_at
                    ON posted_markets(posted_at);

                CREATE INDEX IF NOT EXISTS idx_skipped_condition
                    ON skipped_markets(condition_id);
            """)

    # ------------------------------------------------------------------ #
    # Core deduplication                                                   #
    # ------------------------------------------------------------------ #

    def already_posted(self, condition_id: str, cooldown_hours: int = 48) -> bool:
        """Return True if this market was posted within cooldown_hours.
        48hr default: prevents re-posting the same market while still
        allowing it to resurface if it's still the best market days later.
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT posted_at FROM posted_markets
                WHERE condition_id = ?
                ORDER BY posted_at DESC
                LIMIT 1
                """,
                (condition_id,),
            ).fetchone()

        if not row:
            return False

        posted_at = datetime.fromisoformat(row["posted_at"])
        now = datetime.now(timezone.utc)
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)

        hours_since = (now - posted_at).total_seconds() / 3600
        return hours_since < cooldown_hours

    def record_post(
        self,
        market: dict,
        tweet_text: str,
        market_url: str,
        opentweet_post_id: str = None,
        x_post_url: str = None,
    ):
        """Record a successfully posted market."""
        events = market.get("events", [])
        event_slug = events[0].get("slug", "") if events else ""

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO posted_markets (
                    condition_id, question, slug, event_slug, market_url,
                    probability_pct, volume_24hr, end_date, tweet_text,
                    opentweet_post_id, x_post_url, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market["conditionId"],
                    market["question"],
                    market.get("slug", ""),
                    event_slug,
                    market_url,
                    int(float(market.get("lastTradePrice", 0)) * 100),
                    float(market.get("volume24hr", 0)),
                    market.get("endDateIso", ""),
                    tweet_text,
                    opentweet_post_id,
                    x_post_url,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def record_skip(self, market: dict, reason: str):
        """Record a market that was fetched but not posted, and why."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO skipped_markets (condition_id, question, reason, skipped_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    market.get("conditionId", "unknown"),
                    market.get("question", "unknown"),
                    reason,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def record_feed_snapshot(self, feed: list[dict]):
        """Log what the feed looked like each run for diagnostics."""
        top = feed[0] if feed else {}
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO feed_snapshots (snapped_at, market_count, top_market_question, top_market_volume)
                VALUES (?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    len(feed),
                    top.get("question", ""),
                    float(top.get("volume24hr", 0)),
                ),
            )

    # ------------------------------------------------------------------ #
    # Resolution tracking (accuracy dashboard foundation)                  #
    # ------------------------------------------------------------------ #

    def mark_resolved(self, condition_id: str, resolution: str, was_correct: bool):
        """Mark a market as resolved and whether Arke's take was correct.
        resolution: 'YES' or 'NO'
        was_correct: True if Arke's position matched the resolution
        """
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE posted_markets
                SET resolved = 1, resolution = ?, was_correct = ?
                WHERE condition_id = ?
                """,
                (resolution, 1 if was_correct else 0, condition_id),
            )

    # ------------------------------------------------------------------ #
    # Read queries                                                         #
    # ------------------------------------------------------------------ #

    def get_recent_posts(self, limit: int = 10) -> list[dict]:
        """Return the most recent posts for display or diagnostics."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM posted_markets
                ORDER BY posted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_accuracy_stats(self) -> dict:
        """Return Arke's accuracy track record for the dashboard."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_posted,
                    SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as total_resolved,
                    SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as total_correct,
                    ROUND(
                        100.0 * SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END)
                        / NULLIF(SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END), 0),
                        1
                    ) as accuracy_pct
                FROM posted_markets
                """).fetchone()
        return dict(row) if row else {}

    def get_unresolved_posts(self) -> list[dict]:
        """Return posts where the market has an end_date in the past
        but hasn't been marked resolved yet — for the resolution checker.
        """
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM posted_markets
                WHERE resolved = 0
                AND end_date < date('now')
                ORDER BY end_date ASC
                """).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Quick summary for CLI output."""
        with self._conn() as conn:
            posted = conn.execute("SELECT COUNT(*) FROM posted_markets").fetchone()[0]
            skipped = conn.execute("SELECT COUNT(*) FROM skipped_markets").fetchone()[0]
            snapshots = conn.execute("SELECT COUNT(*) FROM feed_snapshots").fetchone()[
                0
            ]
            last_post = conn.execute(
                "SELECT posted_at, question FROM posted_markets ORDER BY posted_at DESC LIMIT 1"
            ).fetchone()
        return {
            "total_posted": posted,
            "total_skipped": skipped,
            "total_snapshots": snapshots,
            "last_post_at": last_post["posted_at"] if last_post else None,
            "last_post_question": last_post["question"] if last_post else None,
        }
