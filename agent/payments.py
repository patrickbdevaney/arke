"""
agent/payments.py — unified x402 + Circle Nanopayments verifier.

    verify_payment(payment, price_usdc, resource) -> (ok: bool, challenge: dict)

    - No payment            -> (False, 402-challenge advertising both schemes)
    - Nanopayments present  -> verify via the Circle Gateway hosted facilitator
                               (x402-compatible: POST the signed EIP-3009
                               authorization to the facilitator /verify endpoint)
    - x402 present          -> verify via the existing x402 path (fallback)
    - both fail / absent    -> (False, challenge)   (paid means paid)

Design rules (from ARKE_AGENTIC_UPLIFT_SPEC.md):
  * ADDITIVE. Nanopayments only activates when CIRCLE_GATEWAY_FACILITATOR_URL is
    set; otherwise the existing x402 path serves paid endpoints unchanged.
  * NEVER crashes. A missing key, a facilitator that is down, or any network
    error falls back to x402; it never raises into the feed or the MCP server.
  * x402 fallback preserves the feed's historical behaviour exactly: when
    X402_FACILITATOR_URL is unset it fails OPEN (dev mode), and when set it
    POSTs the legacy {payment, price, currency} body and checks `valid`.

Facilitator request shape is the canonical x402 v2 contract — verified against
the coinbase/x402 spec (specs/x402-specification-v2.md, §7.1) and the Circle
Gateway reference (`@circle-fin/x402-batching`, which wraps this same contract):

    POST {facilitator}/verify
    { "x402Version": 2, "paymentPayload": {...}, "paymentRequirements": {...} }
    -> 200 { "isValid": true, "payer": "0x..." }

The buyer sends its PaymentPayload base64-encoded in the X-PAYMENT header (x402
convention); we decode it back to the JSON object the facilitator expects.
"""

import os
import json
import base64
import logging

import httpx

log = logging.getLogger(__name__)

# USDC has 6 decimals (atomic-unit conversion). Network is Arc testnet in CAIP-2
# form (chainId 5042002), formed at call time so ARC_CHAIN_ID can be overridden.
USDC_DECIMALS = 6


def _env(name: str, default: str = "") -> str:
    """Read env at call time (so tests/operators can flip vars without reimport)."""
    return os.getenv(name, default)


def _network() -> str:
    return f"eip155:{_env('ARC_CHAIN_ID', '5042002')}"


def _facilitator() -> str:
    return _env("CIRCLE_GATEWAY_FACILITATOR_URL")


def _atomic(price_usdc: str) -> str:
    """USDC human price -> atomic-unit string (6 decimals). Fails open to '0'."""
    try:
        return str(int(round(float(price_usdc) * (10 ** USDC_DECIMALS))))
    except Exception:
        return "0"


def _pay_to() -> str:
    """Recipient: the Gateway seller wallet if configured, else the x402 addr."""
    return _env("CIRCLE_GATEWAY_SELLER_WALLET") or _env("X402_RECEIVE_ADDRESS")


def _requirements(price_usdc: str, resource: str, scheme: str) -> dict:
    """A single x402 v2 PaymentRequirements entry for one scheme."""
    req = {
        "scheme": scheme,
        "network": _network(),
        "amount": _atomic(price_usdc),          # atomic units (x402 v2)
        "maxAmountRequired": str(price_usdc),    # human USDC (legacy x402 readers)
        "asset": _env("CIRCLE_GATEWAY_USDC_ASSET") or "USDC",
        "payTo": _pay_to(),
        "resource": resource,
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USDC", "version": "2", "human_amount": str(price_usdc)},
    }
    return req


def _challenge(price_usdc: str, resource: str) -> dict:
    """The HTTP-402 body. Advertises x402 always, plus the Nanopayments/Gateway
    scheme when a facilitator is configured."""
    schemes = ["exact"]  # x402 "exact" scheme (EIP-3009)
    if _facilitator():
        schemes.append("nanopayments-gateway")
    return {
        "x402Version": 2,
        "error": "payment required",
        "price": str(price_usdc),
        "currency": "USDC",
        "network": _network(),
        "payTo": _pay_to(),
        "accepts": [_requirements(price_usdc, resource, s) for s in schemes],
    }


def _decode_payment(payment: str) -> dict:
    """Decode the X-PAYMENT header into the PaymentPayload object the facilitator
    expects. x402 base64-encodes the JSON payload; tolerate a raw JSON string or
    an opaque token too. Never raises — returns {} if it can't be parsed."""
    if not payment:
        return {}
    if isinstance(payment, dict):
        return payment
    # Try base64 -> JSON first (the x402 X-PAYMENT convention).
    try:
        decoded = base64.b64decode(payment, validate=False).decode("utf-8")
        obj = json.loads(decoded)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Fall back to a bare JSON string.
    try:
        obj = json.loads(payment)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Opaque token — pass it through so the facilitator can decide.
    return {"raw": payment}


def _verify_nanopayments(payment: str, price_usdc: str, resource: str) -> bool:
    """Verify a signed payment with the Circle Gateway hosted facilitator.

    POSTs the canonical x402 v2 /verify body and treats `isValid`/`valid` true
    as success. Any error -> False (the caller then falls back to x402)."""
    facilitator = _facilitator()
    if not facilitator:
        return False
    try:
        payload = _decode_payment(payment)
        body = {
            "x402Version": 2,
            "paymentPayload": payload,
            "paymentRequirements": _requirements(price_usdc, resource, "exact"),
        }
        headers = {"Content-Type": "application/json"}
        key = _env("CIRCLE_GATEWAY_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = httpx.post(
            f"{facilitator.rstrip('/')}/verify",
            headers=headers,
            json=body,
            timeout=10.0,
        )
        if r.status_code != 200:
            log.warning(
                "[payments] Gateway /verify -> %s (falling back to x402)",
                r.status_code,
            )
            return False
        data = r.json()
        # x402 v2 uses `isValid`; some facilitators use `valid`. Accept either.
        return bool(data.get("isValid", data.get("valid", False)))
    except Exception as e:
        log.warning("[payments] nanopayments verify error (falling back): %s", e)
        return False


def _verify_x402(payment: str, price_usdc: str, resource: str = "") -> bool:
    """The existing x402 verification path — single source of truth, reused by
    the feed (`feed_server._verify_payment` delegates here).

    Preserves the feed's historical semantics exactly:
      * X402_FACILITATOR_URL unset  -> fail OPEN (return True) for local dev.
      * set -> POST the legacy {payment, price, currency} body and check `valid`.
    Never raises — any error returns False."""
    facilitator = _env("X402_FACILITATOR_URL")
    if not facilitator:
        log.warning("[payments] X402_FACILITATOR_URL unset — failing open on verify")
        return True
    try:
        r = httpx.post(
            f"{facilitator.rstrip('/')}/verify",
            json={"payment": payment, "price": str(price_usdc), "currency": "USDC"},
            timeout=10.0,
        )
        return r.status_code == 200 and bool(r.json().get("valid", False))
    except Exception as e:
        log.warning("[payments] x402 verify error: %s", e)
        return False


def verify_payment(payment, price_usdc: str, resource: str = ""):
    """Unified verifier used by BOTH the FastAPI feed and the MCP server.

    Returns (ok, challenge):
      * ok=True, challenge={}             — payment verified
      * ok=False, challenge={402 body}    — no/invalid payment; advertise schemes

    Never crashes: Gateway errors fall back to x402, and x402 itself fails open
    in dev (no facilitator). A genuinely absent payment still returns
    (False, challenge) so paid endpoints stay paid."""
    if not payment:
        return False, _challenge(price_usdc, resource)

    # Nanopayments (Circle Gateway) first when configured.
    if _facilitator() and _verify_nanopayments(payment, price_usdc, resource):
        return True, {}

    # Fall back to the existing x402 path (also covers the no-Gateway case).
    if _verify_x402(payment, price_usdc, resource):
        return True, {}

    return False, _challenge(price_usdc, resource)
