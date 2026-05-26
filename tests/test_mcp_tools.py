"""
tests/test_mcp_tools.py — unit tests for the MCP tool wrappers.

The MCP server is a thin transport layer over existing Arke functions, so each
test mocks the underlying function (imported into agent.mcp_server's namespace)
and asserts the tool returns a well-formed dict. The key invariant: every tool
FAILS OPEN — an exception in the underlying call returns a structured error
dict, never raises. No network, no DB.
"""

import agent.mcp_server as m


def _boom(*_a, **_k):
    raise RuntimeError("underlying failure")


# ------------------------------------------------------------------ #
# Free tools                                                          #
# ------------------------------------------------------------------ #


def test_get_latest_call_shapes(monkeypatch):
    monkeypatch.setattr(m, "get_latest_prediction",
                        lambda: {"condition_id": "0xabc", "question": "q?"})
    monkeypatch.setattr(m, "read_oracle_event", lambda cid: {"resolved": False})
    out = m.get_latest_call()
    assert out["condition_id"] == "0xabc"
    assert out["oracle"] == {"resolved": False}


def test_get_latest_call_no_predictions(monkeypatch):
    monkeypatch.setattr(m, "get_latest_prediction", lambda: None)
    assert m.get_latest_call() == {"error": "no predictions yet"}


def test_get_latest_call_fail_open(monkeypatch):
    monkeypatch.setattr(m, "get_latest_prediction", _boom)
    assert m.get_latest_call() == {"error": "temporarily unavailable"}


def test_get_track_record_shapes(monkeypatch):
    monkeypatch.setattr(m, "get_dual_scores", lambda: {
        "n_resolved": 3, "directional_pct": 67, "skill_bps": 1200,
        "brier": 0.21, "by_category": {"crypto": {"n": 1, "brier": 0.1}},
    })
    monkeypatch.setattr(m, "get_recent_resolutions",
                        lambda limit=10: [{"condition_id": "0x1"}])
    out = m.get_track_record()
    assert out["count"] == 3
    assert out["directional_accuracy_pct"] == 67
    assert out["brier_skill_bps"] == 1200
    assert out["brier"] == 0.21
    assert out["by_category"]["crypto"]["n"] == 1
    assert out["recent"] == [{"condition_id": "0x1"}]


def test_get_track_record_fail_open(monkeypatch):
    monkeypatch.setattr(m, "get_dual_scores", _boom)
    assert m.get_track_record() == {"error": "temporarily unavailable"}


def test_get_calibration_shapes(monkeypatch):
    monkeypatch.setattr(m, "build_calibration_payload",
                        lambda: {"scores": {}, "reliability_bins": [], "note": "n"})
    out = m.get_calibration()
    assert "reliability_bins" in out


def test_get_calibration_fail_open(monkeypatch):
    monkeypatch.setattr(m, "build_calibration_payload", _boom)
    assert m.get_calibration() == {"error": "temporarily unavailable"}


def test_verify_onchain_found(monkeypatch):
    monkeypatch.setattr(m, "read_oracle_event",
                        lambda cid: {"condition_id": cid, "resolved": True})
    out = m.verify_onchain("0xabc")
    assert out["resolved"] is True


def test_verify_onchain_missing(monkeypatch):
    monkeypatch.setattr(m, "read_oracle_event", lambda cid: None)
    assert m.verify_onchain("0xabc") == {
        "error": "no onchain record for that condition_id"
    }


def test_verify_onchain_fail_open(monkeypatch):
    monkeypatch.setattr(m, "read_oracle_event", _boom)
    assert m.verify_onchain("0xabc") == {"error": "temporarily unavailable"}


def test_list_covered_markets_shapes(monkeypatch):
    monkeypatch.setattr(m, "list_active_markets",
                        lambda: [{"condition_id": "0x1"}, {"condition_id": "0x2"}])
    out = m.list_covered_markets()
    assert isinstance(out, list)
    assert out[0]["condition_id"] == "0x1"


def test_list_covered_markets_fail_open(monkeypatch):
    monkeypatch.setattr(m, "list_active_markets", _boom)
    out = m.list_covered_markets()
    assert out == [{"error": "temporarily unavailable"}]


# ------------------------------------------------------------------ #
# Paid tools — payment_required without payment, payload when it clears
# ------------------------------------------------------------------ #


def _gate_fail(*_a, **_k):
    return False, {"x402Version": 2, "accepts": [{"scheme": "exact"}]}


def _gate_pass(*_a, **_k):
    return True, {}


def test_get_market_intelligence_payment_required(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_fail)
    out = m.get_market_intelligence("0xabc", payment=None)
    assert out["payment_required"] is True
    assert out["accepts"][0]["scheme"] == "exact"


def test_get_market_intelligence_paid(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "build_intelligence_payload",
                        lambda cid: {"condition_id": cid, "provenance": {"x": 1}})
    out = m.get_market_intelligence("0xabc", payment="paid")
    assert out["condition_id"] == "0xabc"
    assert "provenance" in out


def test_get_market_intelligence_fail_open(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "build_intelligence_payload", _boom)
    assert m.get_market_intelligence("0xabc", payment="paid") == {
        "error": "temporarily unavailable"
    }


def test_get_prediction_bundle_payment_required(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_fail)
    out = m.get_prediction_bundle("sha256:abc", payment=None)
    assert out["payment_required"] is True


def test_get_prediction_bundle_paid_known(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "get_prediction_by_cid",
                        lambda cid: {"reasoning_cid": cid})
    out = m.get_prediction_bundle("sha256:abc", payment="x")
    assert out["reasoning_cid"] == "sha256:abc"


def test_get_prediction_bundle_paid_unknown(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "get_prediction_by_cid", lambda cid: None)
    assert m.get_prediction_bundle("sha256:abc", payment="x") == {
        "error": "unknown cid"
    }


def test_get_prediction_bundle_fail_open(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "get_prediction_by_cid", _boom)
    assert m.get_prediction_bundle("sha256:abc", payment="x") == {
        "error": "temporarily unavailable"
    }


def test_request_forecast_payment_required(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_fail)
    out = m.request_forecast("0xabc", payment=None)
    assert out["payment_required"] is True


def test_request_forecast_paid(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "enqueue_forecast",
                        lambda cid: {"job_id": 7, "status": "queued",
                                     "eta_seconds": 90})
    out = m.request_forecast("0xabc", payment="x")
    assert out["job_id"] == 7
    assert out["status"] == "queued"


def test_request_forecast_fail_open(monkeypatch):
    monkeypatch.setattr(m, "verify_payment", _gate_pass)
    monkeypatch.setattr(m, "enqueue_forecast", _boom)
    assert m.request_forecast("0xabc", payment="x") == {
        "error": "temporarily unavailable"
    }
