"""
agent/db.py — Arke persistence layer

Production-grade SQLite database for deduplication, audit trail,
accuracy tracking, and operational diagnostics.

Schema is append-only and migration-safe. New columns added with
ALTER TABLE ... ADD COLUMN so existing data is never destroyed.

Usage:
    from agent.db import ArkeDB
    db = ArkeDB()

    if not db.already_posted(condition_id):
        db.record_post(market, tweet, market_url, post_id)
    else:
        db.record_skip(market, "cooldown_48hr")
"""

import sqlite3
import os
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Default to arke.db in the project root (one level above agent/)
DB_PATH = Path(__file__).parent.parent / "arke.db"


class ArkeDB:
    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or DB_PATH)
        self._init()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # concurrent reads
        conn.execute("PRAGMA synchronous=NORMAL")  # safe + fast
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def _init(self):
        """Create all tables and indexes. Idempotent — safe to call every startup."""
        with self._conn() as conn:
            conn.executescript("""
                -- --------------------------------------------------------
                -- Core: every market Arke has posted about
                -- --------------------------------------------------------
                CREATE TABLE IF NOT EXISTS posted_markets (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

                    -- Market identity
                    condition_id        TEXT NOT NULL,
                    question            TEXT NOT NULL,
                    slug                TEXT NOT NULL DEFAULT '',
                    event_slug          TEXT NOT NULL DEFAULT '',
                    market_url          TEXT NOT NULL DEFAULT '',

                    -- Market state at time of posting
                    probability_pct     INTEGER NOT NULL DEFAULT 0,
                    volume_24hr         REAL    NOT NULL DEFAULT 0,
                    volume_total        REAL    NOT NULL DEFAULT 0,
                    liquidity           REAL    NOT NULL DEFAULT 0,
                    end_date            TEXT    NOT NULL DEFAULT '',
                    spread              REAL    NOT NULL DEFAULT 0,

                    -- Tweet content
                    tweet_text          TEXT    NOT NULL DEFAULT '',
                    tweet_take          TEXT    NOT NULL DEFAULT '',   -- text without Bet: line
                    tweet_length        INTEGER NOT NULL DEFAULT 0,

                    -- Distribution
                    opentweet_post_id   TEXT,
                    x_post_url          TEXT,
                    builder_code        TEXT    NOT NULL DEFAULT '',   -- which builder code was active

                    -- Timing
                    posted_at           TEXT    NOT NULL,
                    posted_at_ts        INTEGER NOT NULL DEFAULT 0,    -- unix timestamp for fast range queries

                    -- Resolution tracking (filled in later)
                    resolved            INTEGER NOT NULL DEFAULT 0,    -- 0=open, 1=resolved
                    resolution          TEXT,                          -- 'YES' or 'NO'
                    resolution_date     TEXT,
                    was_correct         INTEGER,                       -- 1=correct, 0=wrong, NULL=unresolved
                    arke_position       TEXT,                          -- 'AGREE' or 'DISAGREE' with market

                    -- Quality
                    quality_score       REAL,                          -- Cerebras adversarial score 0-1
                    quality_passed      INTEGER NOT NULL DEFAULT 1,    -- 1=passed filter, 0=blocked

                    -- Engagement (updated async)
                    x_likes             INTEGER,
                    x_retweets          INTEGER,
                    x_replies           INTEGER,
                    x_impressions       INTEGER,
                    engagement_updated  TEXT
                );

                -- --------------------------------------------------------
                -- Deduplication cooldown index (most-queried path)
                -- --------------------------------------------------------
                CREATE INDEX IF NOT EXISTS idx_posted_condition_at
                    ON posted_markets(condition_id, posted_at DESC);

                CREATE INDEX IF NOT EXISTS idx_posted_at_ts
                    ON posted_markets(posted_at_ts DESC);

                CREATE INDEX IF NOT EXISTS idx_posted_resolved
                    ON posted_markets(resolved, end_date);

                -- --------------------------------------------------------
                -- Skipped markets: why the agent didn't post
                -- --------------------------------------------------------
                CREATE TABLE IF NOT EXISTS skipped_markets (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id        TEXT    NOT NULL DEFAULT '',
                    question            TEXT    NOT NULL DEFAULT '',
                    probability_pct     INTEGER NOT NULL DEFAULT 0,
                    volume_24hr         REAL    NOT NULL DEFAULT 0,
                    reason              TEXT    NOT NULL,
                    skipped_at          TEXT    NOT NULL,
                    skipped_at_ts       INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_skipped_condition
                    ON skipped_markets(condition_id, skipped_at DESC);

                CREATE INDEX IF NOT EXISTS idx_skipped_reason
                    ON skipped_markets(reason);

                -- --------------------------------------------------------
                -- Feed snapshots: what the market feed looked like each run
                -- --------------------------------------------------------
                CREATE TABLE IF NOT EXISTS feed_snapshots (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapped_at          TEXT    NOT NULL,
                    snapped_at_ts       INTEGER NOT NULL DEFAULT 0,
                    market_count        INTEGER NOT NULL DEFAULT 0,
                    actionable_count    INTEGER NOT NULL DEFAULT 0,
                    top_question        TEXT    NOT NULL DEFAULT '',
                    top_volume_24hr     REAL    NOT NULL DEFAULT 0,
                    top_probability_pct INTEGER NOT NULL DEFAULT 0,
                    markets_json        TEXT    NOT NULL DEFAULT '[]'  -- full feed as JSON for replay
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_at
                    ON feed_snapshots(snapped_at_ts DESC);

                -- --------------------------------------------------------
                -- Builder codes: audit trail of which code was used when
                -- --------------------------------------------------------
                CREATE TABLE IF NOT EXISTS builder_codes (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    builder_code        TEXT    NOT NULL UNIQUE,
                    builder_address     TEXT    NOT NULL DEFAULT '',
                    activated_at        TEXT    NOT NULL,
                    deactivated_at      TEXT,
                    reason              TEXT    NOT NULL DEFAULT '',   -- 'initial', 'rotated', 'compromised'
                    is_active           INTEGER NOT NULL DEFAULT 1
                );

                -- --------------------------------------------------------
                -- Operational log: every agent run
                -- --------------------------------------------------------
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at              TEXT    NOT NULL,
                    run_at_ts           INTEGER NOT NULL DEFAULT 0,
                    outcome             TEXT    NOT NULL DEFAULT '',   -- 'posted', 'skipped', 'error', 'dry_run'
                    market_selected     TEXT,
                    error_message       TEXT,
                    duration_ms         INTEGER NOT NULL DEFAULT 0,
                    groq_model          TEXT    NOT NULL DEFAULT '',
                    builder_code        TEXT    NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_runs_at
                    ON agent_runs(run_at_ts DESC);

                CREATE INDEX IF NOT EXISTS idx_runs_outcome
                    ON agent_runs(outcome);
            """)

            # Migration-safe: add new columns to existing deployments
            self._safe_add_columns(conn)

    def _safe_add_columns(self, conn: sqlite3.Connection):
        """Add any columns that don't exist yet. Safe to run on old databases."""
        migrations = [
            ("posted_markets", "tweet_take", "TEXT NOT NULL DEFAULT ''"),
            ("posted_markets", "tweet_length", "INTEGER NOT NULL DEFAULT 0"),
            ("posted_markets", "builder_code", "TEXT NOT NULL DEFAULT ''"),
            ("posted_markets", "posted_at_ts", "INTEGER NOT NULL DEFAULT 0"),
            ("posted_markets", "volume_total", "REAL NOT NULL DEFAULT 0"),
            ("posted_markets", "liquidity", "REAL NOT NULL DEFAULT 0"),
            ("posted_markets", "spread", "REAL NOT NULL DEFAULT 0"),
            ("posted_markets", "arke_position", "TEXT"),
            ("posted_markets", "quality_score", "REAL"),
            ("posted_markets", "quality_passed", "INTEGER NOT NULL DEFAULT 1"),
            ("posted_markets", "x_likes", "INTEGER"),
            ("posted_markets", "x_retweets", "INTEGER"),
            ("posted_markets", "x_replies", "INTEGER"),
            ("posted_markets", "x_impressions", "INTEGER"),
            ("posted_markets", "engagement_updated", "TEXT"),
            ("skipped_markets", "skipped_at_ts", "INTEGER NOT NULL DEFAULT 0"),
            ("skipped_markets", "probability_pct", "INTEGER NOT NULL DEFAULT 0"),
            ("skipped_markets", "volume_24hr", "REAL NOT NULL DEFAULT 0"),
            ("posted_markets", "arke_probability_pct", "INTEGER"),
            ("posted_markets", "news_context", "TEXT NOT NULL DEFAULT ''"),
            ("posted_markets", "divergence_pts", "INTEGER"),
        ]
        existing = {}
        for table, col, typedef in migrations:
            if table not in existing:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
                existing[table] = {r["name"] for r in rows}
            if col not in existing[table]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                    existing[table].add(col)
                    logger.info(f"Migration: added {table}.{col}")
                except Exception as e:
                    logger.warning(f"Migration skipped {table}.{col}: {e}")

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _now_ts(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    # ------------------------------------------------------------------ #
    # Core deduplication                                                   #
    # ------------------------------------------------------------------ #

    def already_posted(self, condition_id: str, cooldown_hours: int = 48) -> bool:
        """Return True if this market was posted within cooldown_hours.

        48hr default prevents re-posting the same market while still
        allowing it to resurface once it's cycled out and back in.
        Set cooldown_hours=0 to always allow re-posting (testing only).
        """
        if cooldown_hours == 0:
            return False

        cutoff_ts = self._now_ts() - (cooldown_hours * 3600)

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT posted_at_ts FROM posted_markets
                WHERE condition_id = ?
                AND posted_at_ts > ?
                ORDER BY posted_at_ts DESC
                LIMIT 1
                """,
                (condition_id, cutoff_ts),
            ).fetchone()

        return row is not None

    def hours_since_posted(self, condition_id: str) -> float | None:
        """Return hours since this market was last posted, or None if never."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT posted_at_ts FROM posted_markets
                WHERE condition_id = ?
                ORDER BY posted_at_ts DESC
                LIMIT 1
                """,
                (condition_id,),
            ).fetchone()

        if not row:
            return None

        elapsed = self._now_ts() - row["posted_at_ts"]
        return elapsed / 3600

    # ------------------------------------------------------------------ #
    # Writing                                                              #
    # ------------------------------------------------------------------ #

    def record_post(
        self,
        market: dict,
        tweet_text: str,
        market_url: str,
        opentweet_post_id: str = None,
        x_post_url: str = None,
        quality_score: float = None,
        quality_passed: bool = True,
        arke_position: str = None,
        arke_probability_pct: int = None,
        news_context: str = "",
    ) -> int:
        """Record a successfully posted market. Returns the row id."""
        events = market.get("events", [])
        event_slug = events[0].get("slug", "") if events else ""
        builder_code = os.getenv("POLY_BUILDER_CODE", "")

        # Parse take (without Bet: line) for storage
        lines = tweet_text.strip().split("\n")
        take_lines = [l for l in lines if not l.strip().startswith("Bet:")]
        take = "\n".join(take_lines).strip()

        market_pct = int(float(market.get("lastTradePrice", 0)) * 100)
        divergence_pts = (
            arke_probability_pct - market_pct
            if arke_probability_pct is not None else None
        )

        now_iso = self._now_iso()
        now_ts = self._now_ts()

        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO posted_markets (
                    condition_id, question, slug, event_slug, market_url,
                    probability_pct, volume_24hr, volume_total, liquidity,
                    end_date, spread, tweet_text, tweet_take, tweet_length,
                    opentweet_post_id, x_post_url, builder_code,
                    posted_at, posted_at_ts, quality_score, quality_passed,
                    arke_position, arke_probability_pct, news_context,
                    divergence_pts
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?
                )
                """,
                (
                    market.get("conditionId", ""),
                    market.get("question", ""),
                    market.get("slug", ""),
                    event_slug,
                    market_url,
                    market_pct,
                    float(market.get("volume24hr", 0)),
                    float(market.get("volume", 0)),
                    float(market.get("liquidity", 0)),
                    market.get("endDateIso", ""),
                    float(market.get("spread", 0)),
                    tweet_text,
                    take,
                    len(tweet_text),
                    opentweet_post_id,
                    x_post_url,
                    builder_code,
                    now_iso,
                    now_ts,
                    quality_score,
                    1 if quality_passed else 0,
                    arke_position,
                    arke_probability_pct,
                    (news_context or "")[:500],
                    divergence_pts,
                ),
            )
            return cursor.lastrowid

    def record_skip(
        self,
        market: dict,
        reason: str,
    ):
        """Record a market that passed the feed filter but was not posted."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO skipped_markets (
                    condition_id, question, probability_pct,
                    volume_24hr, reason, skipped_at, skipped_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market.get("conditionId", "unknown"),
                    market.get("question", "unknown"),
                    int(float(market.get("lastTradePrice", 0)) * 100),
                    float(market.get("volume24hr", 0)),
                    reason,
                    self._now_iso(),
                    self._now_ts(),
                ),
            )

    def record_feed_snapshot(self, feed: list[dict], actionable: list[dict] = None):
        """Log what the feed looked like each run."""
        import json

        top = feed[0] if feed else {}
        actionable = actionable or feed

        # Store minimal market data — enough to replay analysis
        slim = [
            {
                "conditionId": m.get("conditionId", ""),
                "question": m.get("question", ""),
                "lastTradePrice": m.get("lastTradePrice", 0),
                "volume24hr": m.get("volume24hr", 0),
                "endDateIso": m.get("endDateIso", ""),
            }
            for m in feed[:20]  # cap at 20 to keep db size sane
        ]

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO feed_snapshots (
                    snapped_at, snapped_at_ts, market_count, actionable_count,
                    top_question, top_volume_24hr, top_probability_pct, markets_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._now_iso(),
                    self._now_ts(),
                    len(feed),
                    len(actionable),
                    top.get("question", ""),
                    float(top.get("volume24hr", 0)),
                    int(float(top.get("lastTradePrice", 0)) * 100),
                    json.dumps(slim),
                ),
            )

    def record_run(
        self,
        outcome: str,
        market_selected: str = None,
        error_message: str = None,
        duration_ms: int = 0,
    ):
        """Log every agent execution for operational monitoring."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    run_at, run_at_ts, outcome, market_selected,
                    error_message, duration_ms, groq_model, builder_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._now_iso(),
                    self._now_ts(),
                    outcome,
                    market_selected,
                    error_message,
                    duration_ms,
                    os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                    os.getenv("POLY_BUILDER_CODE", ""),
                ),
            )

    def register_builder_code(
        self,
        builder_code: str,
        builder_address: str,
        reason: str = "initial",
    ):
        """Register a builder code as active. Deactivates all previous codes."""
        now = self._now_iso()
        with self._conn() as conn:
            # Deactivate all existing active codes
            conn.execute(
                """
                UPDATE builder_codes
                SET is_active = 0, deactivated_at = ?
                WHERE is_active = 1
                """,
                (now,),
            )
            # Insert new active code (ignore if already exists)
            conn.execute(
                """
                INSERT OR IGNORE INTO builder_codes
                    (builder_code, builder_address, activated_at, reason, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (builder_code, builder_address, now, reason),
            )

    # ------------------------------------------------------------------ #
    # Resolution tracking                                                  #
    # ------------------------------------------------------------------ #

    def mark_resolved(
        self,
        condition_id: str,
        resolution: str,
        was_correct: bool,
        resolution_date: str = None,
    ):
        """Mark all posts for a market as resolved.

        resolution: 'YES' or 'NO'
        was_correct: True if Arke's position matched the resolution
        """
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE posted_markets
                SET resolved = 1,
                    resolution = ?,
                    resolution_date = ?,
                    was_correct = ?
                WHERE condition_id = ?
                AND resolved = 0
                """,
                (
                    resolution,
                    resolution_date or self._now_iso(),
                    1 if was_correct else 0,
                    condition_id,
                ),
            )

    def get_unresolved_past_enddate(self) -> list[dict]:
        """Markets past end date that haven't been marked resolved yet.
        Used by the resolution checker to find markets to close out.
        """
        cutoff = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT condition_id, question, end_date, slug, event_slug
                FROM posted_markets
                WHERE resolved = 0
                AND end_date != ''
                AND end_date < ?
                ORDER BY end_date ASC
                """,
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Read queries                                                         #
    # ------------------------------------------------------------------ #

    def get_recent_posts(self, limit: int = 10) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM posted_markets
                ORDER BY posted_at_ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_accuracy_stats(self) -> dict:
        """Arke's accuracy track record. Core dashboard metric."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                        AS total_posted,
                    SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END)  AS total_resolved,
                    SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) AS total_correct,
                    ROUND(
                        100.0 * SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END)
                        / NULLIF(SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END), 0),
                        1
                    )                                               AS accuracy_pct,
                    ROUND(AVG(volume_24hr), 0)                      AS avg_volume_24hr,
                    ROUND(AVG(probability_pct), 0)                  AS avg_probability_pct
                FROM posted_markets
                """).fetchone()
        return dict(row) if row else {}

    def get_skip_reasons(self) -> list[dict]:
        """Breakdown of why markets were skipped. Useful for tuning filters."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT reason, COUNT(*) as count
                FROM skipped_markets
                GROUP BY reason
                ORDER BY count DESC
                """).fetchall()
        return [dict(r) for r in rows]

    def get_run_stats(self, days: int = 7) -> dict:
        """Operational stats for the last N days."""
        cutoff_ts = self._now_ts() - (days * 86400)
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN outcome = 'posted' THEN 1 ELSE 0 END)  AS posted,
                    SUM(CASE WHEN outcome = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                    SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END)   AS errors,
                    SUM(CASE WHEN outcome = 'dry_run' THEN 1 ELSE 0 END) AS dry_runs,
                    ROUND(AVG(duration_ms), 0)                           AS avg_duration_ms
                FROM agent_runs
                WHERE run_at_ts > ?
                """,
                (cutoff_ts,),
            ).fetchone()
        return dict(row) if row else {}

    def stats(self) -> dict:
        """Quick summary for CLI output on startup."""
        with self._conn() as conn:
            posted = conn.execute("SELECT COUNT(*) FROM posted_markets").fetchone()[0]
            skipped = conn.execute("SELECT COUNT(*) FROM skipped_markets").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
            last = conn.execute("""
                SELECT posted_at, question, probability_pct, volume_24hr
                FROM posted_markets
                ORDER BY posted_at_ts DESC
                LIMIT 1
                """).fetchone()
            accuracy = self.get_accuracy_stats()

        return {
            "total_posted": posted,
            "total_skipped": skipped,
            "total_runs": runs,
            "accuracy_pct": accuracy.get("accuracy_pct"),
            "total_resolved": accuracy.get("total_resolved", 0),
            "last_post_at": last["posted_at"] if last else None,
            "last_post_question": last["question"][:60] if last else None,
            "last_post_pct": last["probability_pct"] if last else None,
            "last_post_vol": last["volume_24hr"] if last else None,
        }

    def print_stats(self):
        """Print a clean summary to stdout. Call on agent startup."""
        s = self.stats()
        print(f"\n{'─'*50}")
        print(f"  Arke DB: {self.db_path}")
        print(f"  Posts:    {s['total_posted']} total | {s['total_resolved']} resolved")
        if s["accuracy_pct"] is not None:
            print(f"  Accuracy: {s['accuracy_pct']}%")
        print(f"  Skipped:  {s['total_skipped']} | Runs: {s['total_runs']}")
        if s["last_post_at"]:
            print(f"  Last:     {s['last_post_question']}")
            print(f"            {s['last_post_pct']}% | ${s['last_post_vol']:,.0f}/24h")
            print(f"            {s['last_post_at'][:19]} UTC")
        print(f"{'─'*50}\n")
