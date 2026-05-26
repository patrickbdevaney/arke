"""
agent/feed_server.py — Arke x402 paid intelligence feed.

A small FastAPI app that exposes Arke's track record. Two tiers:

  free:
    GET /healthz                          liveness
    GET /v1/arke/preview/{condition_id}   market consensus only

  x402-gated (HTTP 402 + payment headers per the x402 spec):
    GET /v1/arke/calls/{condition_id}     $0.001 USDC — full Arke call record
    GET /v1/arke/track-record             $0.01  USDC — summary + all calls

x402 gating is implemented inline (no external package): a missing/invalid
`X-Payment` header yields HTTP 402 with the payment-instruction headers. A
configured facilitator's /verify endpoint validates real payments. Two escape
hatches keep local/dashboard use working:
  * if X402_RECEIVE_ADDRESS is unset → fail open (dev mode)
  * if X-Internal:true + matching X-Internal-Secret → skip payment (dashboard)

Every secret/address is read from the environment — nothing is hardcoded.

Run:  uvicorn agent.feed_server:app --host 0.0.0.0 --port 8402
"""

import os
import time
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent.db import ArkeDB
from agent.feed_helpers import build_calibration_payload
from agent.payments import verify_payment, _verify_x402

log = logging.getLogger(__name__)

app = FastAPI(title="Arke Feed", version="2.0.0")

# The day Arke started operating — surfaced in the track-record summary.
OPERATING_SINCE = "2026-05-18"

PRICE_CALL = os.getenv("X402_PRICE_CALL_USDC", "0.001")
PRICE_TRACK_RECORD = os.getenv("X402_PRICE_TRACKRECORD_USDC", "0.01")


def _db() -> ArkeDB:
    """Open the DB lazily per request. ARKE_DB_PATH overrides the default path
    (used by tests + when running the feed against a copy)."""
    return ArkeDB(os.getenv("ARKE_DB_PATH") or None)


# ------------------------------------------------------------------ #
# x402 payment gating                                                  #
# ------------------------------------------------------------------ #


def _verify_payment(proof: str, price: str) -> bool:
    """Validate an x402 payment proof. Delegates to the unified verifier's x402
    path (agent/payments.py) so there is a single source of truth; behaviour is
    unchanged — fail open when no facilitator is configured, otherwise consult
    it. Kept as a thin wrapper for backward compatibility."""
    return _verify_x402(proof, price)


def _payment_gate(request: Request, price: str, resource: str = ""):
    """Return None if the request may proceed, else a 402 JSONResponse.

    Order: internal dashboard bypass → dev fail-open → payment proof → demand.

    The actual proof check goes through agent.payments.verify_payment, so the
    feed transparently gains Circle Nanopayments verification when
    CIRCLE_GATEWAY_FACILITATOR_URL is set and falls back to x402 otherwise. The
    internal bypass, the dev fail-open, and the 402 response body below are
    unchanged.
    """
    # Dashboard / server-side bypass.
    if request.headers.get("X-Internal") == "true":
        secret = os.getenv("INTERNAL_SECRET")
        if secret and request.headers.get("X-Internal-Secret") == secret:
            return None

    receive = os.getenv("X402_RECEIVE_ADDRESS")
    if not receive:
        # Local dev mode: no receiving address configured → serve for free.
        log.warning("[feed] X402_RECEIVE_ADDRESS unset — serving gated route (dev mode)")
        return None

    proof = request.headers.get("X-Payment")
    ok, _challenge = verify_payment(proof, price, resource=resource)
    if ok:
        return None

    return JSONResponse(
        status_code=402,
        content={
            "error": "payment required",
            "price": price,
            "currency": "USDC",
            "recipient": receive,
        },
        headers={
            "X-Payment-Required": "true",
            "X-Price": str(price),
            "X-Currency": "USDC",
            "X-Recipient": receive,
            "X-Facilitator": os.getenv("X402_FACILITATOR_URL", ""),
        },
    )


# ------------------------------------------------------------------ #
# Shaping                                                              #
# ------------------------------------------------------------------ #


def _call_payload(row: dict) -> dict:
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


def _empty_call(condition_id: str) -> dict:
    """Documented shape with the requested id and everything else null —
    returned (200) when the call isn't in the DB so the gate stays observable."""
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
# Routes                                                               #
# ------------------------------------------------------------------ #


@app.get("/healthz")
def healthz():
    return {"status": "ok", "ts": int(time.time())}


@app.get("/v1/arke/preview/{condition_id}")
def preview(condition_id: str):
    """Free teaser: market consensus only, withholds Arke's estimate."""
    market_pct = None
    for row in _db().get_track_record(limit=500):
        if row.get("condition_id") == condition_id:
            market_pct = row.get("probability_pct")
            break
    return {
        "condition_id": condition_id,
        "market_pct": market_pct,
        "arke_probability": None,
        "message": "pay to see Arke's estimate",
    }


@app.get("/v1/arke/calls/{condition_id}")
def get_call(condition_id: str, request: Request):
    gated = _payment_gate(request, PRICE_CALL, resource=f"/v1/arke/calls/{condition_id}")
    if gated is not None:
        return gated

    for row in _db().get_track_record(limit=1000):
        if row.get("condition_id") == condition_id:
            return _call_payload(row)
    # Payment cleared but no such call — keep 200 so the gate is observable.
    return _empty_call(condition_id)


@app.get("/v1/arke/calibration")
def calibration():
    """Always free. Calibration data is marketing, never a product to gate.

    Body is built by agent.feed_helpers.build_calibration_payload() so the MCP
    server's get_calibration tool returns the exact same shape."""
    return build_calibration_payload()


@app.get("/v1/arke/builder")
def builder_info():
    """Free, ungated. Surfaces Arke's Polymarket builder attribution so the
    dashboard and any client can show where builder fees accrue."""
    address = os.getenv("POLY_BUILDER_ADDRESS", "")
    code = os.getenv("POLY_BUILDER_CODE", "")
    return {
        "builder_address": address or None,
        "builder_code_prefix": (code[:10] + "..." if len(code) > 10 else code) or None,
        "polymarket_profile": (f"https://polymarket.com/profile/{address}"
                               if address else None),
        "fee_rate_bps": 50,
        "note": ("Builder fees (0.5%) accrue on fills from orders submitted "
                 "through arke.live's TradeWidget. builderCode bytes32 is "
                 "injected server-side into every signed EIP-712 order struct."),
    }


@app.get("/v1/arke/track-record")
def track_record(request: Request):
    gated = _payment_gate(request, PRICE_TRACK_RECORD, resource="/v1/arke/track-record")
    if gated is not None:
        return gated

    db = _db()
    summary = db.get_accuracy_summary()
    try:
        brier_by_category = db.get_brier_by_category()
    except Exception as e:
        log.warning(f"[feed] brier_by_category failed: {e}")
        brier_by_category = {}
    try:
        dual = db.get_dual_scores()
    except Exception as e:
        log.warning(f"[feed] dual_scores failed: {e}")
        dual = {"directional_pct": 0, "skill_bps": 0}
    return {
        "summary": {
            "n_total": summary["n_total"],
            "n_resolved": summary["n_resolved"],
            "accuracy_pct": summary["accuracy_pct"],
            "brier_index": summary["brier_index"],
            "brier_by_category": brier_by_category,
            "directional_pct": dual.get("directional_pct", 0),
            "skill_bps": dual.get("skill_bps", 0),
            "source": "sqlite",
            "oracle_contract": os.getenv("ORACLE_CONTRACT_ADDRESS") or None,
            "operating_since": OPERATING_SINCE,
        },
        "calls": [_call_payload(r) for r in db.get_track_record()],
    }
