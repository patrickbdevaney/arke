"""
agent/agents/generator.py — Tweet generation via Groq LLM

Uses openai/gpt-oss-120b (120B MoE, MMLU 90%) on Groq.
Falls back to llama-3.3-70b-versatile if the primary returns empty output.

Provides:
  generate_tweet(market: dict, news_context: str = "") -> str
"""

import os
import logging

from dotenv import load_dotenv
from groq import Groq

from agent.integrations.polymarket import get_market_url, get_event_context

load_dotenv()

logger = logging.getLogger(__name__)

PRIMARY_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = "llama-3.3-70b-versatile"


def _build_prompt(market: dict, news_context: str) -> str:
    price = float(market.get("lastTradePrice", 0.5) or 0.5)
    pct = int(price * 100)
    question = market.get("question", "")
    vol24 = float(market.get("volume24hr", 0) or 0)
    end_date = market.get("endDateIso", "")
    market_url = get_market_url(market)
    context = get_event_context(market)

    news_block = f"\nRelevant news context: {news_context[:400]}" if news_context else ""

    return f"""You are Arke, an autonomous prediction market intelligence agent. You write sharp, analytical tweets that crypto-native traders respect and engage with.

Market: {question}
Current probability: {pct}% YES
24hr volume: ${vol24:,.0f} USDC
Resolves: {end_date}
Context: {context}{news_block}

TWEET STRUCTURE (follow exactly):
Line 1: State the event and the market's implied probability as a fact. One sentence. End with a period.
Line 2: Your take — agree or disagree — with exactly one specific, data-grounded reason. Start with "I think" or "I disagree —". End with a period.
Line 3: "Bet: {market_url}"

RULES:
- Total length under 240 characters including the URL
- The probability must appear as a specific percentage number
- Your reason must be specific — cite a mechanism, a historical pattern, or a named data point. Never vague generalities
- Slightly contrarian is better than agreeing with consensus
- No hashtags, no exclamation marks, no emojis, no ellipses
- No comma splices — each clause is its own sentence
- Do not start with "Market says" — vary the opening
- Return only the tweet text, nothing else

GOOD EXAMPLES:
"MicroStrategy holds $40B in Bitcoin with zero liquidation pressure. Market prices 55% chance they sell by May 31 — that contradicts every public commitment Saylor has made since 2020.
Bet: polymarket.com/event/microstrategy-sell-any-bitcoin-in-2025"

"Strait of Hormuz at 30% normal traffic by June. Iran has closed it twice before and reopened within weeks under economic pressure. The market is underpricing normalization.
Bet: polymarket.com/event/strait-of-hormuz-traffic-2026"

BAD EXAMPLES (never do these):
"Market says 55% chance MicroStrategy sells Bitcoin by May 31, I disagree, Saylor's long term strategy is unchanged" — comma splice, vague reason
"55% YES on MicroStrategy selling BTC! Interesting market! 🔥" — exclamations, emoji, no take"""


def generate_tweet(market: dict, news_context: str = "") -> str:
    """Generate an analytical tweet for `market`. Returns the stripped string."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("[Generator] GROQ_API_KEY not set")
        return ""

    client = Groq(api_key=api_key)
    prompt = _build_prompt(market, news_context)

    try:
        response = client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"[Generator] primary model failed: {e}")
        content = ""

    if content and len(content) >= 20:
        logger.info(f"[Generator] Tweet generated: {len(content)} chars (primary)")
        return content

    # Fallback
    logger.warning(f"[Generator] primary returned empty/short — falling back to {FALLBACK_MODEL}")
    try:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=180,
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"[Generator] fallback model failed: {e}")
        return ""

    logger.info(f"[Generator] Tweet generated: {len(content)} chars (fallback)")
    return content
