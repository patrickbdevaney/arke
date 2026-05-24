"""
tests/test_ensemble.py — unit tests for run_forecaster_ensemble.

The three council forecasters are mocked at the Groq client boundary so the
median-aggregation and fail-open fallback logic can be exercised offline. No
network, no API key beyond the dummy injected via monkeypatch.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent.agents import forecaster_agent
from agent.agents.forecaster_agent import run_forecaster_ensemble


_MARKET = {
    "question": "Will X happen by 2026?",
    "lastTradePrice": 0.50,
    "volume24hr": 50_000,
    "endDateIso": "2026-12-31T00:00:00Z",
}
_URL = "polymarket.com/event/x"


def _resp(pct: int):
    """A Groq completion whose content encodes ARKE_PCT: pct."""
    content = (
        "TWEET:\n"
        f"Market says X at 50%.\n"
        f"Arke estimates {pct}% — specific reason {pct}.\n"
        f"Bet: {_URL}\n"
        f"ARKE_PCT: {pct}"
    )
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


def _groq_with(side_effect):
    """Return a stand-in for groq.Groq whose client.create yields `side_effect`
    (a list of responses and/or Exceptions, one per ensemble config)."""
    client = MagicMock()
    client.chat.completions.create.side_effect = side_effect
    return MagicMock(return_value=client)


def test_median_of_three(monkeypatch):
    """pcts [60, 65, 80] → median 65, tweet from the 65 call."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _groq_with([_resp(60), _resp(65), _resp(80)])
    with patch.object(forecaster_agent, "Groq", groq_cls):
        tweet, pct, cites = run_forecaster_ensemble(_MARKET, "", _URL)
    assert pct == 65
    assert "Arke estimates 65%" in tweet


def test_two_succeed_still_aggregates(monkeypatch):
    """Only 2 forecasters succeed [40, 90] → median 65, function returns."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _groq_with([_resp(40), _resp(90), RuntimeError("boom")])
    with patch.object(forecaster_agent, "Groq", groq_cls):
        tweet, pct, cites = run_forecaster_ensemble(_MARKET, "", _URL)
    assert pct == 65


def test_one_success_falls_back_to_single(monkeypatch):
    """<2 successes → falls back to run_forecaster_agent (not the ensemble)."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _groq_with([_resp(60), RuntimeError("x"), RuntimeError("y")])
    fallback = MagicMock(return_value=("FALLBACK TWEET", 42, []))
    with patch.object(forecaster_agent, "Groq", groq_cls), \
         patch.object(forecaster_agent, "run_forecaster_agent", fallback):
        tweet, pct, cites = run_forecaster_ensemble(_MARKET, "", _URL)
    fallback.assert_called_once()
    assert tweet == "FALLBACK TWEET"
    assert pct == 42


def test_all_fail_falls_back_to_single(monkeypatch):
    """0 successes → falls back to run_forecaster_agent."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _groq_with([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    fallback = MagicMock(return_value=("FALLBACK TWEET", 42, []))
    with patch.object(forecaster_agent, "Groq", groq_cls), \
         patch.object(forecaster_agent, "run_forecaster_agent", fallback):
        tweet, pct, cites = run_forecaster_ensemble(_MARKET, "", _URL)
    fallback.assert_called_once()
    assert tweet == "FALLBACK TWEET"
