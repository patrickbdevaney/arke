"""
tests/test_payments.py — unit tests for the unified x402 + Nanopayments verifier.

All network is mocked. Covers:
  * no payment            -> (False, challenge) advertising x402 ("exact"), plus
                             "nanopayments-gateway" only when the facilitator is set
  * Nanopayments success  -> (True, {})
  * Nanopayments error    -> falls back to x402
  * both fail             -> (False, challenge)
  * the /verify body is the canonical x402 v2 shape (x402Version/paymentPayload/
    paymentRequirements) and checks isValid
  * the x402 fallback preserves the feed's historical semantics (fail open when
    X402_FACILITATOR_URL unset; legacy {payment,price,currency} body + `valid`)
"""

import json

import agent.payments as p


# ------------------------------------------------------------------ #
# Challenge / scheme advertising                                      #
# ------------------------------------------------------------------ #


def test_no_payment_challenge_x402_only(monkeypatch):
    monkeypatch.delenv("CIRCLE_GATEWAY_FACILITATOR_URL", raising=False)
    ok, challenge = p.verify_payment(None, "0.01", "res")
    assert ok is False
    schemes = [a["scheme"] for a in challenge["accepts"]]
    assert "exact" in schemes
    assert "nanopayments-gateway" not in schemes
    assert challenge["x402Version"] == 2
    assert challenge["currency"] == "USDC"


def test_no_payment_challenge_advertises_gateway_scheme_when_set(monkeypatch):
    # When Circle Gateway is configured, the "exact" requirements carry the
    # GatewayWalletBatched `extra` (the verified Circle scheme metadata).
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    ok, challenge = p.verify_payment(None, "0.01", "res")
    assert ok is False
    assert challenge["gateway"] is True
    req = challenge["accepts"][0]
    assert req["scheme"] == "exact"
    assert req["extra"]["name"] == "GatewayWalletBatched"
    assert req["extra"]["version"] == "1"
    assert req["extra"]["verifyingContract"] == p.GATEWAY_WALLET_DEFAULT


def test_challenge_amount_is_atomic_usdc(monkeypatch):
    monkeypatch.delenv("CIRCLE_GATEWAY_FACILITATOR_URL", raising=False)
    _, challenge = p.verify_payment(None, "0.01", "res")
    req = challenge["accepts"][0]
    assert req["amount"] == "10000"          # 0.01 USDC * 1e6
    assert req["maxAmountRequired"] == "0.01"


# ------------------------------------------------------------------ #
# verify_payment routing                                              #
# ------------------------------------------------------------------ #


def test_nanopayments_success(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    monkeypatch.setattr(p, "_verify_nanopayments", lambda *a, **k: True)
    ok, challenge = p.verify_payment("token", "0.01", "res")
    assert ok is True
    assert challenge == {}


def test_nanopayments_error_falls_back_to_x402(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    monkeypatch.setattr(p, "_verify_nanopayments", lambda *a, **k: False)
    # x402 with no facilitator -> fail open True (the fallback succeeds)
    monkeypatch.delenv("X402_FACILITATOR_URL", raising=False)
    ok, challenge = p.verify_payment("token", "0.01", "res")
    assert ok is True
    assert challenge == {}


def test_both_fail_returns_challenge(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    monkeypatch.setattr(p, "_verify_nanopayments", lambda *a, **k: False)
    monkeypatch.setattr(p, "_verify_x402", lambda *a, **k: False)
    ok, challenge = p.verify_payment("token", "0.01", "res")
    assert ok is False
    assert "accepts" in challenge


def test_no_gateway_uses_x402_directly(monkeypatch):
    # No Circle facilitator at all → straight to x402 (which fails open here).
    monkeypatch.delenv("CIRCLE_GATEWAY_FACILITATOR_URL", raising=False)
    monkeypatch.delenv("X402_FACILITATOR_URL", raising=False)
    ok, _ = p.verify_payment("token", "0.01", "res")
    assert ok is True


# ------------------------------------------------------------------ #
# Nanopayments /verify request shape (canonical x402 v2)              #
# ------------------------------------------------------------------ #


class _Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_verify_nanopayments_posts_x402_v2_shape(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example/")
    monkeypatch.setenv("CIRCLE_GATEWAY_API_KEY", "k123")
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Resp(200, {"isValid": True, "payer": "0xabc"})

    monkeypatch.setattr(p.httpx, "post", fake_post)
    assert p._verify_nanopayments("token", "0.01", "res") is True
    assert captured["url"] == "https://fac.example/verify"
    assert captured["headers"]["Authorization"] == "Bearer k123"
    body = captured["json"]
    assert body["x402Version"] == 2
    assert "paymentPayload" in body
    assert body["paymentRequirements"]["scheme"] == "exact"
    assert body["paymentRequirements"]["network"].startswith("eip155:")


def test_verify_nanopayments_invalid(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    monkeypatch.setattr(p.httpx, "post",
                        lambda *a, **k: _Resp(200, {"isValid": False,
                                                    "invalidReason": "insufficient_funds"}))
    assert p._verify_nanopayments("token", "0.01", "res") is False


def test_verify_nanopayments_accepts_legacy_valid_field(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    monkeypatch.setattr(p.httpx, "post",
                        lambda *a, **k: _Resp(200, {"valid": True}))
    assert p._verify_nanopayments("token", "0.01", "res") is True


def test_verify_nanopayments_non_200_returns_false(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")
    monkeypatch.setattr(p.httpx, "post", lambda *a, **k: _Resp(503, {}))
    assert p._verify_nanopayments("token", "0.01", "res") is False


def test_verify_nanopayments_network_error_returns_false(monkeypatch):
    monkeypatch.setenv("CIRCLE_GATEWAY_FACILITATOR_URL", "https://fac.example")

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(p.httpx, "post", boom)
    assert p._verify_nanopayments("token", "0.01", "res") is False


def test_verify_nanopayments_unset_facilitator_returns_false(monkeypatch):
    monkeypatch.delenv("CIRCLE_GATEWAY_FACILITATOR_URL", raising=False)
    assert p._verify_nanopayments("token", "0.01", "res") is False


# ------------------------------------------------------------------ #
# x402 fallback preserves the feed's historical behaviour             #
# ------------------------------------------------------------------ #


def test_verify_x402_fail_open_when_unset(monkeypatch):
    monkeypatch.delenv("X402_FACILITATOR_URL", raising=False)
    assert p._verify_x402("anyproof", "0.01") is True


def test_verify_x402_consults_facilitator_legacy_body(monkeypatch):
    monkeypatch.setenv("X402_FACILITATOR_URL", "https://x402.example")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp(200, {"valid": True})

    monkeypatch.setattr(p.httpx, "post", fake_post)
    assert p._verify_x402("proof", "0.01") is True
    assert captured["url"] == "https://x402.example/verify"
    assert captured["json"] == {"payment": "proof", "price": "0.01",
                                "currency": "USDC"}


def test_verify_x402_network_error_returns_false(monkeypatch):
    monkeypatch.setenv("X402_FACILITATOR_URL", "https://x402.example")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(p.httpx, "post", boom)
    assert p._verify_x402("proof", "0.01") is False
