"""
agent/agents/signal_agent.py — Signal aggregation agent

Takes raw headlines and market data.
Produces structured signal report for the Forecaster.
"""

import os
import hashlib
import logging
from datetime import datetime, timezone
from groq import Groq

log = logging.getLogger(__name__)
MODEL = "llama-3.3-70b-versatile"


def _h_title(h) -> str:
    return h if isinstance(h, str) else (h.get("title", "") or "")


def _h_url(h) -> str:
    return "" if isinstance(h, str) else (h.get("url", "") or "")


def _build_citations(headlines: list) -> list:
    """One citation per used headline: claim=title, source_url (or ''), and the
    sha256 of the title text for tamper-evidence."""
    now = datetime.now(timezone.utc).isoformat()
    cites = []
    for h in headlines[:8]:
        title = _h_title(h)
        if not title:
            continue
        cites.append({
            "claim": title,
            "source_url": _h_url(h),
            "retrieved_at": now,
            "content_sha256": hashlib.sha256(title.encode("utf-8")).hexdigest(),
        })
    return cites


def run_signal_agent(market: dict, headlines: list) -> tuple[str, list]:
    """
    Aggregate signals for a market. Returns (report, citations).
    `headlines` items may be plain title strings or {title,url,source} dicts.
    Falls back to ("", citations) on LLM failure (pipeline continues without
    a report but keeps the citations it already retrieved).
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not headlines:
        return "", []

    citations = _build_citations(headlines)

    question = market.get("question", "")
    pct = int(float(market.get("lastTradePrice", 0)) * 100)
    vol = float(market.get("volume24hr", 0))
    end = market.get("endDateIso", "")

    headline_block = "\n".join(f"- {_h_title(h)}" for h in headlines[:8])

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
        log.info(
            f"[SignalAgent] Report generated ({len(report)} chars), "
            f"{len(citations)} citations"
        )
        return report, citations
    except Exception as e:
        log.warning(f"[SignalAgent] Failed: {e} — continuing without signal report")
        return "", citations
