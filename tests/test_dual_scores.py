"""
tests/test_dual_scores.py — off-chain dual (directional + Brier skill) scoring.

All against a temporary SQLite DB seeded with resolved calls; nothing touches
the real arke.db and no chain/network is involved.
"""

from agent.db import ArkeDB


def _seed(db: ArkeDB, cid: str, arke_pct: int, resolution: str) -> None:
    """Record a posted call and mark it resolved with the given outcome."""
    market = {
        "conditionId": cid,
        "question": f"Will event {cid} happen?",
        "slug": cid,
        "events": [{"slug": cid}],
        "lastTradePrice": 0.50,
        "volume24hr": 50_000,
        "endDateIso": "2026-12-31T00:00:00Z",
    }
    db.record_post(market, "line1\nline2", f"polymarket.com/event/{cid}",
                   arke_probability_pct=arke_pct)
    db.mark_resolved(cid, resolution, (arke_pct >= 50) == (resolution == "YES"))


def test_correct_high_confidence_call_positive_skill(tmp_path):
    """85% → YES: directional 100%, large positive skill vs flat-50%."""
    db = ArkeDB(str(tmp_path / "dual.db"))
    _seed(db, "0x1", 85, "YES")
    s = db.get_dual_scores()
    assert s["directional_pct"] == 100
    assert s["skill_bps"] > 0          # ~ +9100 for a single 85% YES hit
    assert s["n_resolved"] == 1
    assert s["brier"] is not None


def test_wrong_call_negative_skill(tmp_path):
    """30% → YES is a wrong NO call: directional 0%, negative skill."""
    db = ArkeDB(str(tmp_path / "dual.db"))
    _seed(db, "0x2", 30, "YES")
    s = db.get_dual_scores()
    assert s["directional_pct"] == 0
    assert s["skill_bps"] < 0
    assert s["n_resolved"] == 1


def test_one_correct_one_wrong_is_fifty_pct(tmp_path):
    """One hit + one miss → 50% directional."""
    db = ArkeDB(str(tmp_path / "dual.db"))
    _seed(db, "0x1", 85, "YES")   # correct
    _seed(db, "0x2", 30, "YES")   # wrong
    s = db.get_dual_scores()
    assert s["directional_pct"] == 50
    assert s["n_resolved"] == 2


def test_empty_db_returns_zeros_no_exception(tmp_path):
    """No resolved calls → all-zero structure, never raises."""
    db = ArkeDB(str(tmp_path / "dual.db"))
    s = db.get_dual_scores()
    assert s == {
        "directional_pct": 0,
        "skill_bps": 0,
        "brier": None,
        "n_resolved": 0,
        "by_category": {},
    }
