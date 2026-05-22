"""
agent/agents/adversary_agent.py — Adversarial validation agent

Takes the Forecaster's tweet and tries to find factual errors
or logical gaps. Forces a rewrite if it finds problems.
Uses a different model architecture for uncorrelated errors.
"""

import os
import re
import logging
from groq import Groq

log = logging.getLogger(__name__)
MODEL = "qwen/qwen3-32b"
MAX_REWRITES = 1  # one rewrite attempt maximum — no infinite loops


def run_adversary_agent(
    tweet: str,
    market: dict,
    market_url: str,
) -> tuple[str, bool]:
    """
    Adversarially validate the forecaster's tweet.

    Returns:
        (final_tweet, passed)
        passed: True if tweet survived adversary review
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return tweet, True  # fail open if no key

    question = market.get("question", "")
    market_pct = int(float(market.get("lastTradePrice", 0)) * 100)

    prompt = f"""You are an adversarial fact-checker for prediction market analysis.
Your job is to find specific factual errors or logical gaps in prediction market tweets.
You are rigorous and skeptical. You do not pass vague reasoning.

Market: {question}
Market probability: {market_pct}% YES

Tweet to evaluate:
{tweet}

Find ONE of the following if present:
1. A factual claim that is demonstrably wrong
2. A cited year/event that didn't happen or is misattributed
3. Reasoning that directly contradicts the probability estimate
4. A vague claim disguised as a specific fact

If you find a problem: respond with REWRITE: followed by a corrected version
that fixes the specific error while keeping the same structure.

If the reasoning is sound and facts are verifiable: respond with exactly PASS

Respond with ONLY "PASS" or "REWRITE: [corrected tweet]" — nothing else."""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            # qwen3-32b is a reasoning model; give room for thinking + verdict
            # so the answer isn't truncated (which would force a fail-open).
            max_tokens=1024,
        )
        result = (response.choices[0].message.content or "").strip()
        # qwen3 may inline its chain-of-thought in <think>...</think> — strip it
        # so the PASS/REWRITE verdict is what we actually match on.
        result = re.sub(r"<think>[\s\S]*?</think>", "", result, flags=re.IGNORECASE).strip()

        if result.upper().startswith("PASS"):
            log.info("[Adversary] PASS — reasoning validated")
            return tweet, True
        elif result.upper().startswith("REWRITE:"):
            rewritten = result[8:].strip()
            if len(rewritten) > 20 and "Bet:" in rewritten:
                log.info(f"[Adversary] REWRITE — corrected tweet")
                return rewritten, True
            else:
                log.warning("[Adversary] Rewrite malformed — using original")
                return tweet, True
        else:
            log.warning(f"[Adversary] Unexpected response: {result[:50]} — passing")
            return tweet, True

    except Exception as e:
        log.warning(f"[Adversary] Failed: {e} — passing original")
        return tweet, True
