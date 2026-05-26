"""
agent/mcp_server.py — Arke as an MCP server.

Exposes Arke's prediction intelligence as MCP tools callable from Claude Desktop,
Cursor, Cline, Continue, and any MCP client. Five FREE tools return the public
track record / calibration / latest call / onchain verification / covered
markets. Three PAID tools (x402 / Circle Nanopayments, sub-cent USDC) return
full provenance bundles and on-demand forecasts.

STDIO transport. Logs to stderr ONLY (stdout carries JSON-RPC; writing to it
corrupts the protocol). Fails open: every tool wraps an existing Arke function
and returns a structured error dict on any underlying error — it never crashes
the server. This layer is a thin transport wrapper; all business logic lives in
agent.db / agent.feed_helpers / agent.integrations.oracle / agent.payments.
"""

import os
import sys
import logging

# stderr logging ONLY — never stdout on a stdio MCP server.
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("arke-mcp")

# Load .env so the server sees the same feed/oracle/Gateway config as the agent
# when launched standalone (stdio). Never prints to stdout.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception as e:  # pragma: no cover - dotenv always present in practice
    log.warning("dotenv not loaded: %s", e)

from mcp.server.fastmcp import FastMCP

# Reuse existing Arke internals — NO new business logic here.
from agent.db import (
    get_dual_scores,
    get_latest_prediction,
    get_prediction_by_cid,
    list_active_markets,
    get_recent_resolutions,
)
from agent.integrations.oracle import read_oracle_event
from agent.feed_helpers import (
    build_calibration_payload,
    build_intelligence_payload,
)
from agent.payments import verify_payment
from agent.ondemand import enqueue_forecast

mcp = FastMCP(
    name="arke",
    instructions=(
        "Arke is an autonomous prediction-market intelligence agent on Arc. "
        "It forecasts Polymarket markets, logs every call onchain before the "
        "outcome, and scores itself with a Brier skill score. Free tools return "
        "the public track record, calibration curve, and latest call. Paid tools "
        "(sub-cent USDC via x402/Nanopayments) return full provenance bundles and "
        "on-demand forecasts."
    ),
)

# ---- FREE TOOLS ----


@mcp.tool()
def get_latest_call() -> dict:
    """Arke's most recent calibrated probability call, with onchain tx and reasoning hash."""
    try:
        row = get_latest_prediction()
        if not row:
            return {"error": "no predictions yet"}
        return {**row, "oracle": read_oracle_event(row.get("condition_id", ""))}
    except Exception as e:
        log.warning("get_latest_call failed: %s", e)
        return {"error": "temporarily unavailable"}


@mcp.tool()
def get_track_record() -> dict:
    """Prediction count, resolved count, Brier skill score (Murphy 1973), directional accuracy."""
    try:
        s = get_dual_scores()
        return {
            "count": s.get("n_resolved", 0),
            "directional_accuracy_pct": s.get("directional_pct", 0),
            "brier_skill_bps": s.get("skill_bps", 0),
            "brier": s.get("brier"),
            "by_category": s.get("by_category", {}),
            "recent": get_recent_resolutions(limit=10),
        }
    except Exception as e:
        log.warning("get_track_record failed: %s", e)
        return {"error": "temporarily unavailable"}


@mcp.tool()
def get_calibration() -> dict:
    """10-bin reliability diagram and dual scores (always free)."""
    try:
        return build_calibration_payload()
    except Exception as e:
        log.warning("get_calibration failed: %s", e)
        return {"error": "temporarily unavailable"}


@mcp.tool()
def verify_onchain(condition_id: str) -> dict:
    """Verify a Polymarket condition_id was logged onchain by Arke before resolution."""
    try:
        return read_oracle_event(condition_id) or {
            "error": "no onchain record for that condition_id"
        }
    except Exception as e:
        log.warning("verify_onchain failed: %s", e)
        return {"error": "temporarily unavailable"}


@mcp.tool()
def list_covered_markets() -> list[dict]:
    """Markets Arke is currently covering or monitoring (calls not yet resolved)."""
    try:
        return list_active_markets()
    except Exception as e:
        log.warning("list_covered_markets failed: %s", e)
        return [{"error": "temporarily unavailable"}]


# ---- PAID TOOLS (x402 / Nanopayments) ----


@mcp.tool()
def get_market_intelligence(condition_id: str, payment: str | None = None) -> dict:
    """[PAID ~$0.01 USDC] Full council output for a market: signal summary, forecaster
    probability, adversary disputes, filter score, citations w/ hashes, baserate class."""
    ok, challenge = verify_payment(
        payment, price_usdc="0.01", resource="get_market_intelligence"
    )
    if not ok:
        return {"payment_required": True, **challenge}
    try:
        return build_intelligence_payload(condition_id)
    except Exception as e:
        log.warning("get_market_intelligence failed: %s", e)
        return {"error": "temporarily unavailable"}


@mcp.tool()
def get_prediction_bundle(reasoning_cid: str, payment: str | None = None) -> dict:
    """[PAID ~$0.005 USDC] Full provenance bundle (inputs, citations, council outputs)."""
    ok, challenge = verify_payment(
        payment, price_usdc="0.005", resource="get_prediction_bundle"
    )
    if not ok:
        return {"payment_required": True, **challenge}
    try:
        return get_prediction_by_cid(reasoning_cid) or {"error": "unknown cid"}
    except Exception as e:
        log.warning("get_prediction_bundle failed: %s", e)
        return {"error": "temporarily unavailable"}


@mcp.tool()
def request_forecast(condition_id: str, payment: str | None = None) -> dict:
    """[PAID ~$0.05 USDC] Enqueue an on-demand council run for an arbitrary Polymarket market.
    Returns a job id; poll get_prediction_bundle once complete. Rate-limited."""
    ok, challenge = verify_payment(
        payment, price_usdc="0.05", resource="request_forecast"
    )
    if not ok:
        return {"payment_required": True, **challenge}
    try:
        return enqueue_forecast(condition_id)
    except Exception as e:
        log.warning("request_forecast failed: %s", e)
        return {"error": "temporarily unavailable"}


def main():
    """Launch the stdio MCP server (entry point: `arke-mcp` / `python -m agent.mcp_server`)."""
    log.info("Arke MCP server starting (stdio) — 5 free tools, 3 paid")
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
