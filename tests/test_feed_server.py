"""
tests/test_feed_server.py — FastAPI TestClient coverage for the x402 feed.

Each test runs against a temporary SQLite DB (ARKE_DB_PATH) seeded with one
call, so nothing touches the real arke.db.
"""

import pytest
from fastapi.testclient import TestClient

from agent.db import ArkeDB
from agent.feed_server import app

client = TestClient(app)

_CID = "0xseed0001"


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A temp DB with one posted call; points the feed server at it."""
    db_path = tmp_path / "feed_test.db"
    db = ArkeDB(str(db_path))
    market = {
        "conditionId": _CID,
        "question": "Will the seed event happen?",
        "slug": "seed-event",
        "events": [{"slug": "seed-event"}],
        "lastTradePrice": 0.40,   # market 40%
        "volume24hr": 50_000,
        "endDateIso": "2026-12-31T00:00:00Z",
    }
    db.record_post(
        market,
        tweet_text="line1\nline2\nBet: polymarket.com/event/seed-event",
        market_url="polymarket.com/event/seed-event",
        x_post_url="https://x.com/arke_ai/status/1",
        arke_probability_pct=25,  # Arke 25% → call NO, divergence -1500 bps
    )
    monkeypatch.setenv("ARKE_DB_PATH", str(db_path))
    return _CID


def test_healthz_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_preview_returns_market_pct(seeded_db):
    r = client.get(f"/v1/arke/preview/{seeded_db}")
    assert r.status_code == 200
    body = r.json()
    assert "market_pct" in body
    assert body["market_pct"] == 40


def test_calls_402_when_receive_address_set_and_no_payment(seeded_db, monkeypatch):
    monkeypatch.setenv("X402_RECEIVE_ADDRESS", "0xRecipientAddress")
    monkeypatch.delenv("INTERNAL_SECRET", raising=False)
    r = client.get(f"/v1/arke/calls/{seeded_db}")
    assert r.status_code == 402
    assert r.headers.get("X-Payment-Required") == "true"
    assert r.headers.get("X-Recipient") == "0xRecipientAddress"


def test_calls_fail_open_when_no_receive_address(seeded_db, monkeypatch):
    monkeypatch.delenv("X402_RECEIVE_ADDRESS", raising=False)
    r = client.get(f"/v1/arke/calls/{seeded_db}")
    assert r.status_code == 200
    body = r.json()
    assert body["condition_id"] == seeded_db
    assert body["arke_probability"] == 25
    assert body["market_probability"] == 40
    assert body["divergence_bps"] == -1500
    assert body["arke_call"] == "NO"


def test_internal_bypass_skips_payment(seeded_db, monkeypatch):
    monkeypatch.setenv("X402_RECEIVE_ADDRESS", "0xRecipientAddress")
    monkeypatch.setenv("INTERNAL_SECRET", "topsecret")
    r = client.get(
        "/v1/arke/track-record",
        headers={"X-Internal": "true", "X-Internal-Secret": "topsecret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["source"] == "sqlite"
    assert body["summary"]["n_total"] >= 1
