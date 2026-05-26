"""
agent/feed_helpers.py — importable payload builders.

Extracted so BOTH the FastAPI feed (agent/feed_server.py) and the MCP server
(agent/mcp_server.py) call the SAME shaping logic instead of duplicating it.
These functions are pure reads over the DB and the on-disk provenance traces —
no payment gating, no business logic. The feed routes call these; the MCP tools
call these. Behaviour of the feed is unchanged: the calibration route now just
returns build_calibration_payload().

Every function opens the DB lazily and honours ARKE_DB_PATH, exactly like the
feed server's per-request `_db()`, so tests can point at a temporary DB.
"""

import os
import json
import logging
from pathlib import Path

from agent.db import ArkeDB
from agent.provenance import DEFAULT_TRACES_DIR

log = logging.getLogger(__name__)

# The day Arke started operating — surfaced in calibration/track-record.
OPERATING_SINCE = "2026-05-18"


def _db() -> ArkeDB:
    """Open the DB lazily per call. ARKE_DB_PATH overrides the default path."""
    return ArkeDB(os.getenv("ARKE_DB_PATH") or None)


# ------------------------------------------------------------------ #
# Call-record shaping (mirrors the feed's public call shape)          #
# ------------------------------------------------------------------ #


def call_payload(row: dict) -> dict:
    """Map a get_track_record() row to the public call record shape."""
    call_yes = row.get("arke_call_yes")
    arke_call = None if call_yes is None else ("YES" if call_yes else "NO")
    return {
        "condition_id": row.get("condition_id"),
        "question": row.get("question"),
        "arke_probability": row.get("arke_probability_pct"),
        "market_probability": row.get("probability_pct"),
        "divergence_bps": row.get("divergence_bps"),
        "arke_call": arke_call,
        "source_citations": [],
        "reasoning_cid": row.get("reasoning_cid"),
        "resolved": bool(row.get("resolved")),
        "outcome": row.get("resolution"),
        "was_correct": (
            None if row.get("was_correct") is None else bool(row.get("was_correct"))
        ),
        "oracle_log_tx": row.get("oracle_log_tx"),
        "oracle_resolve_tx": row.get("oracle_resolve_tx"),
        "stake_tx": row.get("stake_tx"),
        "posted_at": row.get("posted_at"),
        "x_post_url": row.get("x_post_url"),
    }


def empty_call(condition_id: str) -> dict:
    """Documented shape with the requested id and everything else null."""
    return {
        "condition_id": condition_id,
        "question": None,
        "arke_probability": None,
        "market_probability": None,
        "divergence_bps": None,
        "arke_call": None,
        "source_citations": [],
        "reasoning_cid": None,
        "resolved": False,
        "outcome": None,
        "was_correct": None,
        "oracle_log_tx": None,
        "oracle_resolve_tx": None,
        "stake_tx": None,
        "posted_at": None,
        "x_post_url": None,
    }


# ------------------------------------------------------------------ #
# Provenance trace loading                                            #
# ------------------------------------------------------------------ #


def load_trace(condition_id: str) -> dict | None:
    """Load the sha256-pinned provenance bundle for a condition_id from
    {traces_dir}/{condition_id[:16]}.json. Returns None if absent/unreadable."""
    if not condition_id:
        return None
    try:
        path = Path(DEFAULT_TRACES_DIR) / f"{condition_id[:16]}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except Exception as e:
        log.warning("[feed_helpers] trace load failed for %s: %s", condition_id, e)
        return None


# ------------------------------------------------------------------ #
# Payload builders (shared by the feed routes and the MCP tools)      #
# ------------------------------------------------------------------ #


def build_calibration_payload() -> dict:
    """10-bin reliability diagram + dual scores. Always free.

    Byte-for-byte the body the /v1/arke/calibration route used to inline."""
    db = _db()
    scores = db.get_dual_scores()
    rows = [r for r in db.get_track_record(limit=1000)
            if r.get("resolved") and r.get("resolution") in ("YES", "NO")
            and r.get("arke_probability_pct") is not None]
    bins = [{"bin": i, "lo": i * 10, "hi": i * 10 + 10, "n": 0, "yes": 0}
            for i in range(10)]
    for r in rows:
        b = min(9, int(r["arke_probability_pct"]) // 10)
        bins[b]["n"] += 1
        if r["resolution"] == "YES":
            bins[b]["yes"] += 1
    for b in bins:
        b["empirical_pct"] = (round(100 * b["yes"] / b["n"])
                              if b["n"] else None)
    return {"scores": scores, "reliability_bins": bins,
            "operating_since": OPERATING_SINCE,
            "note": ("skill_bps measures Arke vs a flat-50% reference — "
                     "positive means Arke outperformed random. "
                     "directional_pct measures whether the binary call was right.")}


def build_intelligence_payload(condition_id: str) -> dict:
    """Full intelligence for a market: the public call record joined with its
    sha256-pinned provenance bundle (council signal, forecast, citations w/
    hashes). This is the [PAID] get_market_intelligence MCP tool's body and is a
    pure read — never gated here; the caller does the payment check."""
    db = _db()
    row = None
    for r in db.get_track_record(limit=1000):
        if r.get("condition_id") == condition_id:
            row = r
            break
    payload = call_payload(row) if row else empty_call(condition_id)
    bundle = load_trace(condition_id)
    return {
        **payload,
        "has_record": row is not None,
        "provenance": bundle,
        "provenance_available": bundle is not None,
        "operating_since": OPERATING_SINCE,
    }
