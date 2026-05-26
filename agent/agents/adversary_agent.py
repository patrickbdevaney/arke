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


def reframe_around_evidence(
    tweet: str,
    market: dict,
    market_url: str,
    evidence: str,
) -> tuple[str, bool]:
    """Last-resort reframe after the quality filter blocks the forecaster's
    call 3 times.

    Rather than abandoning the cycle, hand the adversary the single strongest
    grounded evidence block and instruct it to rebuild the call around what that
    evidence actually supports — flipping the directional claim (and the % ) if
    the evidence points the other way. The original forecaster framing was
    rejected as a non-sequitur; here the evidence drives the direction instead
    of the other way around.

    Returns (reframed_tweet, ok). ok=False (and the original tweet) when there is
    no key, no evidence, or no usable rewrite — the caller then re-runs the
    quality filter on the result and only exits if that also fails.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not evidence:
        return tweet, False

    question = market.get("question", "")
    market_pct = int(float(market.get("lastTradePrice", 0)) * 100)

    prompt = f"""You are Arke's adversarial editor. A prediction-market tweet was
REJECTED by the quality filter because its cited reason did not actually argue
for its probability estimate (a non-sequitur). Do not defend the old framing.
Rebuild the call from the grounded evidence below.

Market: {question}
Market probability: {market_pct}% YES

GROUNDED EVIDENCE (the only verifiable source available — anchor on this):
{evidence}

REJECTED tweet:
{tweet}

Your task:
1. Read what the grounded evidence ACTUALLY supports about this market.
2. Pick the probability the evidence points to. You MAY flip the direction of
   the original call if the evidence contradicts it — follow the evidence, not
   the old tweet.
3. Write a NEW 3-line tweet whose line-2 reason is drawn directly from the
   evidence, so the cited fact plainly implies the estimate's direction.

FORMAT (follow exactly):
Line 1: State the market and the market's probability as fact. One sentence.
Line 2: "Arke estimates [X]% — " then ONE specific fact from the evidence that
        directly implies X. No vague patterns. No analogies to unrelated events.
Line 3: "Bet: {market_url}"

Under 260 characters. No hashtags, emojis, or exclamation marks.
Respond with ONLY the 3-line tweet — nothing else."""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            # qwen3-32b is a reasoning model; leave room for thinking + tweet.
            max_tokens=1024,
        )
        result = (response.choices[0].message.content or "").strip()
        result = re.sub(r"<think>[\s\S]*?</think>", "", result, flags=re.IGNORECASE).strip()
        # Strip a leading "TWEET:" label if the model adds one.
        if result.upper().startswith("TWEET:"):
            result = result[6:].strip()

        if len(result) > 20 and "Bet:" in result:
            log.info("[Adversary] Evidence-anchored reframe produced a new call")
            return result, True
        log.warning("[Adversary] Reframe malformed — keeping original")
        return tweet, False

    except Exception as e:
        log.warning(f"[Adversary] Reframe failed: {e} — keeping original")
        return tweet, False
