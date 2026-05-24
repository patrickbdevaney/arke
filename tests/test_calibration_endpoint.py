"""
tests/test_calibration_endpoint.py — the free /v1/arke/calibration route.

Runs against a temporary SQLite DB (ARKE_DB_PATH) seeded with resolved calls;
the endpoint is ungated (calibration is never paywalled), so no payment headers
are needed.
"""

import pytest
from fastapi.testclient import TestClient

from agent.db import ArkeDB
from agent.feed_server import app

client = TestClient(app)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db_path = tmp_path / "calib.db"
    db = ArkeDB(str(db_path))

    def seed(cid, arke_pct, resolution):
        market = {
            "conditionId": cid,
            "question": f"Will {cid} resolve YES?",
            "slug": cid,
            "events": [{"slug": cid}],
            "lastTradePrice": 0.50,
            "volume24hr": 50_000,
            "endDateIso": "2026-12-31T00:00:00Z",
        }
        db.record_post(market, "l1\nl2", f"polymarket.com/event/{cid}",
                       arke_probability_pct=arke_pct)
        db.mark_resolved(cid, resolution, (arke_pct >= 50) == (resolution == "YES"))

    seed("0x1", 85, "YES")   # lands in bin 8 (80–90)
    seed("0x2", 25, "NO")    # lands in bin 2 (20–30)
    monkeypatch.setenv("ARKE_DB_PATH", str(db_path))
    return db_path


def test_returns_ten_bins(seeded_db):
    r = client.get("/v1/arke/calibration")
    assert r.status_code == 200
    bins = r.json()["reliability_bins"]
    assert len(bins) == 10
    assert [b["bin"] for b in bins] == list(range(10))


def test_empty_bins_have_null_empirical(seeded_db):
    bins = client.get("/v1/arke/calibration").json()["reliability_bins"]
    # bin 5 (50–60%) has no calls seeded → empirical_pct must be null
    assert bins[5]["n"] == 0
    assert bins[5]["empirical_pct"] is None
    # bin 8 has the 85% YES call → empirical 100%
    assert bins[8]["n"] == 1
    assert bins[8]["empirical_pct"] == 100


def test_scores_present(seeded_db):
    scores = client.get("/v1/arke/calibration").json()["scores"]
    assert "skill_bps" in scores
    assert "directional_pct" in scores
    assert scores["n_resolved"] == 2
    # both calls are directionally correct → 100%
    assert scores["directional_pct"] == 100
