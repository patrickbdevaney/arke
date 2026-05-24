"""
tests/test_coverage_filters.py — fetch_arke_feed() filtering + 500-market pull.

httpx is mocked: a fake async client returns a fixed market list and records
the request params, so no network call is made.
"""

import asyncio

import agent.integrations.polymarket as pm


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeClient:
    """Stand-in for httpx.AsyncClient as an async context manager."""
    captured: dict = {}
    data: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        _FakeClient.captured["url"] = url
        _FakeClient.captured["params"] = params or {}
        return _FakeResp(_FakeClient.data)


def _mkt(cid, *, price, vol=50_000, liq=30_000, spread=0.02, q=None):
    return {
        "conditionId": cid,
        "question": q or f"Will {cid} resolve YES?",
        "lastTradePrice": price,
        "volume24hr": vol,
        "liquidity": liq,
        "spread": spread,
        "endDateIso": "2026-12-31T00:00:00Z",
    }


def _run(monkeypatch, markets):
    _FakeClient.data = markets
    _FakeClient.captured = {}
    monkeypatch.setattr(pm.httpx, "AsyncClient", _FakeClient)
    feed = asyncio.run(pm.fetch_arke_feed())
    return {m["conditionId"] for m in feed}


def test_probability_band_5_to_95(monkeypatch):
    markets = [
        _mkt("lo_edge", price=0.05),   # 5%  — accepted (boundary)
        _mkt("hi_edge", price=0.95),   # 95% — accepted (boundary)
        _mkt("too_low", price=0.04),   # 4%  — rejected
        _mkt("too_high", price=0.96),  # 96% — rejected
        _mkt("mid", price=0.50),       # 50% — accepted
    ]
    ids = _run(monkeypatch, markets)
    assert {"lo_edge", "hi_edge", "mid"} <= ids
    assert "too_low" not in ids
    assert "too_high" not in ids


def test_quality_gates_volume_liquidity_spread(monkeypatch):
    markets = [
        _mkt("good", price=0.40),                      # passes all gates
        _mkt("thin_vol", price=0.40, vol=5_000),       # vol < 10k  → reject
        _mkt("thin_liq", price=0.40, liq=10_000),      # liq < 25k  → reject
        _mkt("wide_spread", price=0.40, spread=0.06),  # spread ≥ 5c → reject
    ]
    ids = _run(monkeypatch, markets)
    assert "good" in ids
    assert "thin_vol" not in ids
    assert "thin_liq" not in ids
    assert "wide_spread" not in ids


def test_sports_rejected(monkeypatch):
    markets = [
        _mkt("politics", price=0.40, q="Will the Senate pass the bill?"),
        _mkt("sports", price=0.40, q="Will the Lakers beat the Celtics?"),
    ]
    ids = _run(monkeypatch, markets)
    assert "politics" in ids
    assert "sports" not in ids


def test_requests_500_markets(monkeypatch):
    _run(monkeypatch, [_mkt("good", price=0.40)])
    assert _FakeClient.captured["params"].get("limit") == 500
