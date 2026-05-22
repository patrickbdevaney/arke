"""
agent/agents/signal_agent.py — Signal aggregation agent

Takes raw headlines and market data.
Produces structured signal report for the Forecaster.
"""

import os
import logging
from groq import Groq

log = logging.getLogger(__name__)
MODEL = "llama-3.3-70b-versatile"


def run_signal_agent(market: dict, headlines: list[str]) -> str:
    """
    Aggregate signals for a market. Returns structured report string.
    Falls back to empty string on failure (pipeline continues without context).
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not headlines:
        return ""

    question = market.get("question", "")
    pct = int(float(market.get("lastTradePrice", 0)) * 100)
    vol = float(market.get("volume24hr", 0))
    end = market.get("endDateIso", "")

    headline_block = "\n".join(f"- {h}" for h in headlines[:8])

    prompt = f"""You are a signal aggregation agent for prediction markets.

Market: {question}
Current probability: {pct}% YES
24hr volume: ${vol:,.0f}
Resolves: {end}

Relevant news headlines:
{headline_block}

Produce a structured signal report with:
1. KEY SIGNAL: The single most important headline and what it implies for this market
2. DIRECTION: Does the news push probability UP or DOWN from {pct}%?
3. BASE RATE: What is the historical base rate for this type of event? Give a specific number if you know it.
4. SUGGESTED ESTIMATE: What probability would you assign based on this evidence? Give a specific number.

Keep the entire report under 200 words. Be specific. Cite years and numbers."""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        report = (response.choices[0].message.content or "").strip()
        log.info(f"[SignalAgent] Report generated ({len(report)} chars)")
        return report
    except Exception as e:
        log.warning(f"[SignalAgent] Failed: {e} — continuing without signal report")
        return ""
