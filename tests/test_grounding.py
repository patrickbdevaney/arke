"""
tests/test_grounding.py — unit tests for the grounded forecasting inputs.

Everything here is fully offline: httpx is monkeypatched per module, the
base-rate LLM classifier is mocked, and ACLED's token machinery is exercised
without touching the network or the on-disk token cache. The point of every
test is the fail-open contract — a missing key, a bad response, or a thrown
exception must yield ('', []) (or an all-None dict) and never raise.
"""

from unittest.mock import MagicMock

import pytest

from agent import baserates
from agent.baserates import (
    get_base_rate, format_base_rate_block, _keyword_match, REFERENCE_CLASSES,
)
from agent.integrations import clob, research, fred, deribit, acled
from agent.integrations.clob import get_microstructure, extract_yes_token_id
from agent.integrations.research import research_market
from agent.integrations.fred import macro_context
from agent.integrations.deribit import crypto_context
from agent.integrations.acled import geo_context
from agent.calibration import extremize, calibrate


_BY_ID = {e["id"]: e for e in REFERENCE_CLASSES}


# ── shared httpx stand-ins ──────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _Client:
    """Context-manager stand-in for httpx.Client. `routes` maps a URL substring
    to a _Resp (or a 0-arg callable returning one). Records every call."""

    def __init__(self, routes, calls):
        self._routes = routes
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _match(self, url):
        for frag, resp in self._routes.items():
            if frag in url:
                return resp
        return _Resp(404, {})

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        r = self._match(url)
        return r() if callable(r) else r

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        r = self._match(url)
        return r() if callable(r) else r


def _client_factory(routes, calls):
    return lambda *a, **k: _Client(routes, calls)


# ── base rates ──────────────────────────────────────────────────────────────

def test_base_rate_incumbent_keyword_fallback(monkeypatch):
    """LLM unavailable → keyword fallback finds the measured incumbent class."""
    monkeypatch.setattr(baserates, "_llm_classify", lambda q: None)
    entry = get_base_rate("Will the incumbent president win re-election?")
    assert entry is not None
    assert entry["id"] == "incumbent-president-reelection"
    assert entry["confidence"] == "measured"
    assert entry["value_pct"] == 74


def test_base_rate_crypto_threshold_is_redirect(monkeypatch):
    """LLM classifies a price-threshold question → redirect, no number."""
    monkeypatch.setattr(
        baserates, "_llm_classify", lambda q: _BY_ID["crypto-price-threshold"]
    )
    entry = get_base_rate("Will BTC be above $100,000 by June?")
    assert entry["id"] == "crypto-price-threshold"
    assert entry["confidence"] == "redirect"
    assert entry["value_pct"] is None


def test_base_rate_conflict_is_prior(monkeypatch):
    """LLM unavailable → keyword fallback finds the prior conflict class."""
    monkeypatch.setattr(baserates, "_llm_classify", lambda q: None)
    entry = get_base_rate("Will Iran close its airspace?")
    assert entry["id"] == "conflict-escalation-near-term"
    assert entry["confidence"] == "prior"


def test_base_rate_no_match_returns_none(monkeypatch):
    """LLM says 'none' (→ None) and no keyword matches → None."""
    monkeypatch.setattr(baserates, "_llm_classify", lambda q: None)
    assert get_base_rate("Will it rain in Tokyo tomorrow?") is None


def test_base_rate_semantic_generalisation(monkeypatch):
    """A paraphrase with NO matching keyword is still classified by the LLM."""
    paraphrase = "Will the sitting leader keep the top job after the vote?"
    # Prove the keyword fallback alone would miss it.
    assert _keyword_match(paraphrase) is None
    monkeypatch.setattr(
        baserates, "_llm_classify",
        lambda q: _BY_ID["incumbent-president-reelection"],
    )
    entry = get_base_rate(paraphrase)
    assert entry is not None
    assert entry["id"] == "incumbent-president-reelection"


def test_base_rate_classify_fails_open_without_key(monkeypatch):
    """_llm_classify with no GROQ key returns None and never raises."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert baserates._llm_classify("anything") is None


def test_confidence_tier_prompt_text():
    assert "MEASURED — real historical" in format_base_rate_block(
        _BY_ID["incumbent-president-reelection"])
    assert "ROUGH PRIOR" in format_base_rate_block(
        _BY_ID["conflict-escalation-near-term"])
    assert "BASE RATE NOTE" in format_base_rate_block(
        _BY_ID["crypto-price-threshold"])


# ── CLOB microstructure ─────────────────────────────────────────────────────

def test_extract_yes_token_id_from_json_string():
    assert extract_yes_token_id({"clobTokenIds": '["abc","def"]'}) == "abc"


def test_extract_yes_token_id_missing():
    assert extract_yes_token_id({}) == ""


def test_get_microstructure_empty_token_all_none():
    out = get_microstructure("")
    assert out == {"midpoint": None, "spread": None, "best_bid": None,
                   "best_ask": None, "book_hash": None}


# ── per-market research (Brave → Tavily) ────────────────────────────────────

def test_research_market_no_keys_fails_open(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert research_market({"question": "Will X happen?"}) == ("", [])


def test_research_market_brave_results_hash_full_snippet(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "test-key")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    payload = {"web": {"results": [
        {"title": "T1", "url": "https://a.example", "description": "snippet one"},
        {"title": "T2", "url": "https://b.example", "description": "snippet two"},
    ]}}
    calls = []
    monkeypatch.setattr(
        research.httpx, "Client",
        _client_factory({"api.search.brave.com": _Resp(200, payload)}, calls),
    )
    summary, cites = research_market({"question": "Will X happen?"})
    assert summary != ""
    assert len(cites) == 2
    # content_sha256 hashes the full snippet, not the title.
    assert all(c["content_sha256"] for c in cites)
    assert cites[0]["content_sha256"] == research._sha256("snippet one")


# ── FRED macro grounding ────────────────────────────────────────────────────

def test_macro_context_no_key_fails_open(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert macro_context("Will unemployment exceed 5%?") == ("", [])


def test_macro_context_returns_series(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    payload = {"observations": [{"value": "4.2", "date": "2026-04-01"}]}
    calls = []
    monkeypatch.setattr(
        fred.httpx, "Client",
        _client_factory({"stlouisfed.org": _Resp(200, payload)}, calls),
    )
    ctx, cites = macro_context("Will unemployment exceed 5%?")
    assert "UNRATE" in ctx and "4.2" in ctx
    assert cites and cites[0]["source_url"].endswith("UNRATE")


def test_macro_context_skips_dot_sentinel(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    payload = {"observations": [{"value": ".", "date": "2026-04-01"}]}
    calls = []
    monkeypatch.setattr(
        fred.httpx, "Client",
        _client_factory({"stlouisfed.org": _Resp(200, payload)}, calls),
    )
    assert macro_context("Will unemployment exceed 5%?") == ("", [])


# ── ACLED conflict grounding ────────────────────────────────────────────────

def test_geo_context_no_creds_fails_open(monkeypatch):
    monkeypatch.delenv("ACLED_EMAIL", raising=False)
    monkeypatch.delenv("ACLED_PASSWORD", raising=False)
    assert geo_context("Iran airspace") == ("", [])


def test_geo_context_happy_path(monkeypatch):
    monkeypatch.setattr(acled, "_get_token", lambda: "tok")
    payload = {"data": [{"fatalities": 2}, {"fatalities": 0}]}
    monkeypatch.setattr(acled.httpx, "get",
                        lambda *a, **k: _Resp(200, payload))
    ctx, cites = geo_context("Iran airspace")
    # 2 rows summed → "recorded 2 conflict/protest events (2 fatalities)".
    assert "Iran" in ctx and "recorded 2 conflict/protest events" in ctx
    assert cites and cites[0]["source_url"] == "https://acleddata.com/"


def test_acled_token_fast_path_uses_cache(monkeypatch):
    """A fresh cached access token is returned with no network call."""
    import time
    monkeypatch.setenv("ACLED_EMAIL", "e@x.com")
    monkeypatch.setenv("ACLED_PASSWORD", "pw")
    monkeypatch.setattr(acled, "_load", lambda: {
        "access_token": "cached", "access_exp": time.time() + 100000,
    })
    post = MagicMock()
    monkeypatch.setattr(acled.httpx, "post", post)
    assert acled._get_token() == "cached"
    post.assert_not_called()


def test_acled_token_refresh_path_skips_password(monkeypatch):
    """Expired access + valid refresh → refresh used, password auth not."""
    import time
    monkeypatch.setenv("ACLED_EMAIL", "e@x.com")
    monkeypatch.setenv("ACLED_PASSWORD", "pw")
    monkeypatch.setattr(acled, "_load", lambda: {
        "access_token": "old", "access_exp": time.time() - 10,
        "refresh_token": "r", "refresh_exp": time.time() + 100000,
    })
    monkeypatch.setattr(acled, "_save", lambda d: None)
    refresh = MagicMock(return_value={"access_token": "new", "refresh_token": "r2"})
    pwauth = MagicMock()
    monkeypatch.setattr(acled, "_refresh_auth", refresh)
    monkeypatch.setattr(acled, "_password_auth", pwauth)
    assert acled._get_token() == "new"
    refresh.assert_called_once()
    pwauth.assert_not_called()


def test_acled_401_clears_cache(monkeypatch):
    """A 401 from the read endpoint deletes the token cache and fails open."""
    monkeypatch.setattr(acled, "_get_token", lambda: "tok")
    monkeypatch.setattr(acled.httpx, "get", lambda *a, **k: _Resp(401, {}))
    fake_cache = MagicMock()
    monkeypatch.setattr(acled, "CACHE_PATH", fake_cache)
    assert geo_context("Iran airspace") == ("", [])
    fake_cache.unlink.assert_called_once()


# ── Deribit option-implied probability ──────────────────────────────────────

def test_crypto_context_fetches_option_chain(monkeypatch):
    routes = {
        "get_index_price": _Resp(200, {"result": {"index_price": 100000}}),
        "get_instruments": _Resp(200, {"result": [
            {"option_type": "call", "strike": 100000,
             "instrument_name": "BTC-30JUN-100000-C"},
        ]}),
        "get_order_book": _Resp(200, {"result": {"greeks": {"delta": 0.5}}}),
    }
    calls = []
    monkeypatch.setattr(deribit.httpx, "Client", _client_factory(routes, calls))
    ctx, cites = crypto_context("Will BTC be above $100,000?")
    # It detected BTC/100000 and pulled the option chain.
    assert any("get_instruments" in url for _, url, _ in calls)
    assert "DERIBIT" in ctx and "50%" in ctx
    assert cites and "deribit.com" in cites[0]["source_url"]


def test_crypto_context_non_crypto_fails_open():
    assert crypto_context("Will the Fed cut rates?") == ("", [])


# ── calibration ─────────────────────────────────────────────────────────────

def test_extremize_pushes_high_up():
    assert extremize(85) > 85
    assert extremize(85) <= 100


def test_extremize_pushes_low_down():
    assert extremize(15) < 15
    assert extremize(15) >= 0


def test_calibrate_empty_uses_extremize():
    out = calibrate(70, [])
    assert isinstance(out, int)
    assert out == extremize(70)


def test_calibrate_under_50_resolved_uses_extremize():
    resolved = [{"arke_pct": 70, "outcome_yes": True}] * 49
    assert calibrate(70, resolved) == extremize(70)
