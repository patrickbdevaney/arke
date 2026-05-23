"""
tests/test_filter_directional.py — unit test for the filter's `directional` axis.

Verifies that a take whose cited evidence is real/specific but makes NO
directional argument (directional≈0.1) is pushed below PASS_THRESHOLD even
when factual/specific/credible are otherwise strong.

No real API calls and no env vars required — the Groq client is mocked and the
API key is injected via monkeypatch so the filter does not fail open.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from agent.agents.filter import quality_check, PASS_THRESHOLD


def _mock_groq_class(payload: dict):
    """Return a stand-in for `groq.Groq` whose client yields `payload` as the
    JSON message content of a single completion choice."""
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = response
    return MagicMock(return_value=client)


_MARKET = {"question": "Will X happen by 2026?", "lastTradePrice": 0.5}


def test_non_sequitur_evidence_is_blocked(monkeypatch):
    """factual/specific/credible all 0.8 but directional 0.1 → composite < 0.65."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _mock_groq_class({
        "factual": 0.8,
        "specific": 0.8,
        "directional": 0.1,
        "credible": 0.8,
        "reason": "real named event but no argument for the direction",
    })
    with patch("agent.agents.filter.Groq", groq_cls):
        score, passed, _reason = quality_check("a tweet", _MARKET)

    # 0.8*0.25 + 0.8*0.30 + 0.1*0.30 + 0.8*0.15 = 0.59
    assert score == pytest.approx(0.59, abs=1e-9)
    assert score < PASS_THRESHOLD
    assert passed is False


def test_directional_evidence_passes(monkeypatch):
    """Same strong scores but directional 0.9 → composite clears the threshold."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _mock_groq_class({
        "factual": 0.8,
        "specific": 0.8,
        "directional": 0.9,
        "credible": 0.8,
        "reason": "base rate directly implies the estimate",
    })
    with patch("agent.agents.filter.Groq", groq_cls):
        score, passed, _reason = quality_check("a tweet", _MARKET)

    # 0.8*0.25 + 0.8*0.30 + 0.9*0.30 + 0.8*0.15 = 0.83
    assert score == pytest.approx(0.83, abs=1e-9)
    assert passed is True


def test_missing_directional_key_defaults_to_half(monkeypatch):
    """When the model omits `directional`, the parsed default of 0.5 is used."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    groq_cls = _mock_groq_class({
        "factual": 0.0,
        "specific": 0.0,
        "credible": 0.0,
        "reason": "no directional field emitted",
    })
    with patch("agent.agents.filter.Groq", groq_cls):
        score, passed, _reason = quality_check("a tweet", _MARKET)

    # only the 0.5 default * 0.30 weight contributes
    assert score == pytest.approx(0.15, abs=1e-9)
    assert passed is False
