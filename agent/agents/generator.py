"""
agent/agents/generator.py — Tweet generation via Groq LLM

Primary: llama-3.3-70b-versatile (reliable, fast, strong instruction following)
Fallback: llama-3.1-8b-instant (always available, smaller but functional)

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

PRIMARY_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
FALLBACK_MODEL = "llama-3.1-8b-instant"
MAX_TOKENS = 280


def _build_prompt(market: dict, news_context: str) -> str:
    price = float(market.get("lastTradePrice", 0.5) or 0.5)
    pct = int(price * 100)
    question = market.get("question", "")
    vol24 = float(market.get("volume24hr", 0) or 0)
    end_date = market.get("endDateIso", "")
    market_url = get_market_url(market)
    context = get_event_context(market)

    news_block = (
        f"\nRelevant news context: {news_context[:300]}" if news_context else ""
    )

    return f"""You are Arke, an autonomous prediction market intelligence agent. Write a sharp analytical tweet.

Market: {question}
Probability: {pct}% YES
Volume: ${vol24:,.0f} USDC/24h
Resolves: {end_date}
Context: {context}{news_block}

TWEET STRUCTURE (3 lines exactly):
Line 1: State the event and probability as a fact. One sentence ending with a period.
Line 2: Your take starting with "I think" or "I disagree —". One specific data-grounded reason. End with a period.
Line 3: "Bet: {market_url}"

RULES:
- Under 240 characters total including URL
- Specific data point or historical pattern in line 2 — no vague generalities
- No hashtags, exclamation marks, emojis, or ellipses
- No comma splices
- Return only the 3-line tweet, nothing else

EXAMPLE:
Iran closing its airspace has a market-implied probability of 31%.
I disagree — Iran has never sustained an airspace closure beyond 72 hours without reopening under economic pressure from its own airlines.
Bet: polymarket.com/event/iran-closes-its-airspace-by?ref=0x310072d29a53aa0650e09628005a4704e9c4b0d0"""


def generate_tweet(market: dict, news_context: str = "") -> str:
    """Generate an analytical tweet for `market`. Returns stripped string or empty on failure."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.error("[Generator] GROQ_API_KEY not set")
        return ""

    client = Groq(api_key=api_key)
    prompt = _build_prompt(market, news_context)

    # Primary model
    try:
        response = client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=MAX_TOKENS,
        )
        content = (response.choices[0].message.content or "").strip()
        if content and len(content) >= 20:
            logger.info(f"[Generator] {len(content)} chars (primary: {PRIMARY_MODEL})")
            return content
        logger.warning(
            f"[Generator] primary returned empty/short ({len(content)} chars)"
        )
    except Exception as e:
        logger.warning(f"[Generator] primary failed: {e}")

    # Fallback model
    logger.warning(f"[Generator] falling back to {FALLBACK_MODEL}")
    try:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=MAX_TOKENS,
        )
        content = (response.choices[0].message.content or "").strip()
        if content and len(content) >= 20:
            logger.info(
                f"[Generator] {len(content)} chars (fallback: {FALLBACK_MODEL})"
            )
            return content
        logger.error(f"[Generator] fallback also returned empty/short")
    except Exception as e:
        logger.error(f"[Generator] fallback failed: {e}")

    return ""
