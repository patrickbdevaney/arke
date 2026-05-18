"""
agent/agents/filter.py — Adversarial quality filter via Cerebras

Uses qwen-3-235b-a22b-instruct-2507 on Cerebras (235B MoE, different family from Groq).
Different model family = genuine adversarial disagreement possible.

Provides:
  quality_check(tweet: str, market: dict) -> tuple[float, bool, str]
    Returns: (score 0-1, passed bool, reason string)
"""

import os
import re
import json
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "qwen-3-235b-a22b-instruct-2507")
THRESHOLD = 0.65


def _build_prompt(tweet: str, market: dict) -> str:
    question = market.get("question", "")
    price = float(market.get("lastTradePrice", 0.5) or 0.5)
    pct = int(price * 100)
    vol24 = float(market.get("volume24hr", 0) or 0)

    return f"""You are a strict fact-checker for prediction market analysis tweets.

Tweet to evaluate:
{tweet}

Market: {question} — {pct}% YES probability, ${vol24:,.0f} daily volume

Score this tweet 0.0-1.0 on three dimensions:
1. Factual accuracy of any specific claims made (0-1). Penalize invented statistics, wrong dates, fabricated events.
2. Specificity of reasoning (0-1). Does it cite a named mechanism, historical pattern, or real data point?
3. Analytical credibility (0-1). Would a sophisticated prediction market trader find this credible?

IMPORTANT: If the tweet contains a specific numerical claim (e.g. "sold 0.4% of BTC", "12% of Bitcoin holdings"), that claim MUST be verifiable from public knowledge about the subject. If you cannot verify it, score factual accuracy as 0.2 or lower.

Return ONLY valid JSON: {{"score": 0.0, "factual": 0.0, "specific": 0.0, "credible": 0.0, "reason": "one sentence explanation"}}"""


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction from LLM output."""
    if not text:
        return None
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first {...} block
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def quality_check(tweet: str, market: dict) -> tuple[float, bool, str]:
    """Score tweet quality via Cerebras. Fail-open on errors."""
    api_key = os.getenv("CEREBRAS_API_KEY")
    if not api_key:
        logger.info("[Filter] CEREBRAS_API_KEY not set — fail-open")
        return (0.8, True, "filter_skipped_no_key")

    try:
        from cerebras.cloud.sdk import Cerebras
    except Exception as e:
        logger.warning(f"[Filter] cerebras SDK import failed: {e} — fail-open")
        return (0.75, True, "filter_sdk_missing")

    prompt = _build_prompt(tweet, market)

    try:
        client = Cerebras(api_key=api_key)
        resp = client.chat.completions.create(
            model=CEREBRAS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"[Filter] Cerebras call failed: {e} — fail-open")
        return (0.75, True, "filter_error_fail_open")

    parsed = _extract_json(content)
    if not parsed:
        logger.warning(f"[Filter] unparseable response: {content[:200]} — fail-open")
        return (0.75, True, "filter_unparseable_fail_open")

    factual = float(parsed.get("factual", 0.0) or 0.0)
    specific = float(parsed.get("specific", 0.0) or 0.0)
    credible = float(parsed.get("credible", 0.0) or 0.0)
    reason = str(parsed.get("reason", ""))[:240]

    score = factual * 0.5 + specific * 0.25 + credible * 0.25
    passed = score >= THRESHOLD

    logger.info(f"[Filter] Score: {score:.2f} | passed: {passed} | Reason: {reason}")
    return (score, passed, reason)
