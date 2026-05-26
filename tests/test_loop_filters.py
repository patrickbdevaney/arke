"""
tests/test_loop_filters.py — selection-stage gates in the live loop
(prove_the_loop.py): sports exclusion (FIX 1), viability (FIX 3), and
pick_best_market() filtering + the FIX 4 reframe helpers.

Pure-function tests only: no network, no LLM. pick_best_market() reads cooldown
from the real ArkeDB, so every fake market here uses an unknown conditionId
(never posted → never in cooldown), isolating the sports/viability gates.
"""

import datetime

import prove_the_loop as P


# ── FIX 1: tightened sports keywords ────────────────────────────────────────

def test_is_sports_single_team_soccer_now_caught():
    # The Juventus/West Ham/Getafe class: single-team phrasings with no "vs".
    assert P.is_sports("Will Getafe avoid relegation this season?")
    assert P.is_sports("Juventus to win Serie A?")
    assert P.is_sports("Will West Ham stay up?")
    assert P.is_sports("Real Madrid title odds")


def test_is_sports_added_leagues():
    assert P.is_sports("Who wins the Premier League?")
    assert P.is_sports("La Liga top scorer?")
    assert P.is_sports("Will the Champions League final go to penalties?")
    assert P.is_sports("NBA MVP race")


def test_is_sports_does_not_flag_real_markets():
    assert not P.is_sports("Will Bitcoin close above $100k by June?")
    assert not P.is_sports("Will the Fed cut rates in July?")
    assert not P.is_sports("US x Iran permanent peace deal by May 31, 2026?")


# ── FIX 3: viability_score ───────────────────────────────────────────────────

def test_viability_rejects_ungroundable_types():
    assert not P.viability_score("How many times will Elon Musk tweet next week?")
    assert not P.viability_score("Will the movie gross over $1B at the box office?")
    assert not P.viability_score("Will the song hit #1 on the Billboard Hot 100?")
    assert not P.viability_score("Will the show be the Netflix top series?")
    # sports are non-viable too
    assert not P.viability_score("Will Getafe avoid relegation?")


def test_viability_accepts_grounded_markets():
    assert P.viability_score("Will Bitcoin close above $100k by June?")
    assert P.viability_score("Will the Fed cut rates in July?")
    assert P.viability_score("Will Iran close its airspace by May 24?")


# ── FIX 1 + 2 + 3: pick_best_market selection-stage gating ───────────────────

def _mkt(cid, q, days, vol=50_000):
    end = (datetime.date.today() + datetime.timedelta(days=days)).isoformat() + "T00:00:00Z"
    return {"conditionId": cid, "question": q, "lastTradePrice": 0.4,
            "volume24hr": vol, "endDateIso": end}


def test_pick_skips_sports_and_nonviable_picks_urgent():
    feed = [
        _mkt("zz_sport", "Will Getafe avoid relegation?", 3),
        _mkt("zz_tweet", "How many tweets will Elon post?", 2),
        _mkt("zz_btc", "Will Bitcoin close above $100k by June?", 5),
        _mkt("zz_fed", "Will the Fed cut rates this year?", 200),
    ]
    sel = P.pick_best_market(feed)
    assert sel is not None
    assert sel["conditionId"] == "zz_btc"  # urgent + viable beats long-dated


def test_pick_returns_none_when_all_filtered():
    feed = [
        _mkt("zz_s1", "Will the Lakers beat the Celtics?", 3),
        _mkt("zz_s2", "Will the movie top the box office?", 2),
    ]
    assert P.pick_best_market(feed) is None


def test_pick_empty_feed_is_none():
    assert P.pick_best_market([]) is None


def test_pick_long_dated_fallback():
    feed = [_mkt("zz_fed2", "Will the Fed cut rates this year?", 200)]
    sel = P.pick_best_market(feed)
    assert sel is not None and sel["conditionId"] == "zz_fed2"


# ── FIX 4 helpers: strongest-evidence ranking + arke_pct re-parse ────────────

def test_strongest_evidence_prefers_measured_base_rate():
    blocks = [
        "ORDERBOOK: midpoint 40% (last-trade 41%), spread 1.2c.",
        "RESEARCH:\nReuters reports talks stalled (2026-05-20).",
        "BASE RATE [x] (MEASURED — real historical frequency, citable): ~8%.",
    ]
    assert P._strongest_evidence(blocks).startswith("BASE RATE")


def test_strongest_evidence_research_over_orderbook():
    blocks = [
        "ORDERBOOK: midpoint 40%.",
        "RESEARCH:\nlong research block with substance",
    ]
    assert P._strongest_evidence(blocks).startswith("RESEARCH")


def test_strongest_evidence_empty():
    assert P._strongest_evidence([]) == ""


def test_parse_arke_pct_from_estimate_line():
    t = "Market sits at 41% YES.\nArke estimates 12% — closed once since 2015.\nBet: x"
    assert P._parse_arke_pct(t, 41) == 12


def test_parse_arke_pct_falls_back_to_default():
    t = "Line one.\nNo estimate here at all.\nBet: x"
    assert P._parse_arke_pct(t, 41) == 41
