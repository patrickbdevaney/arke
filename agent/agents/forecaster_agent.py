"""
agent/agents/forecaster_agent.py — Probability forecaster agent

Takes market data and signal report.
Produces a tweet with a specific Arke probability estimate
that diverges from (or confirms) the market consensus.
The probability estimate is the core product signal.
"""

import os
import re
import logging
from groq import Groq

log = logging.getLogger(__name__)
MODEL = "openai/gpt-oss-120b"


def run_forecaster_agent(
    market: dict,
    signal_report: str,
    market_url: str,
) -> tuple[str, int]:
    """
    Generate analytical tweet with specific probability estimate.

    Returns:
        (tweet_text, arke_probability_pct)
        arke_probability_pct: Arke's estimate (may differ from market)
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "", 0

    question = market.get("question", "")
    market_pct = int(float(market.get("lastTradePrice", 0)) * 100)
    vol = float(market.get("volume24hr", 0))
    end = market.get("endDateIso", "")

    signal_block = f"\nSIGNAL REPORT:\n{signal_report}" if signal_report else ""

    prompt = f"""You are Arke, an autonomous prediction market intelligence agent.
You apply superforecasting methodology: reference class thinking, base rates,
specific mechanisms. You produce calibrated probability estimates.

Market: {question}
Market consensus: {market_pct}% YES
24hr volume: ${vol:,.0f}
Resolves: {end}{signal_block}

Your task:
1. Assess whether the market consensus of {market_pct}% is correct
2. Produce YOUR probability estimate (can agree or disagree with market)
3. Write a 3-line tweet

TWEET FORMAT (follow exactly):
Line 1: State the market and the market's probability as fact. One sentence.
Line 2: "Arke estimates [X]% — " followed by one specific cited reason.
         X is YOUR probability estimate based on evidence.
         The reason MUST cite a specific year, named event, or number.
         Example: "Arke estimates 8% — Iran has only fully closed airspace
         once since 2015, reopening within 48h after ICAO pressure in March 2020."
Line 3: "Bet: {market_url}"

RULES:
- Under 260 characters total
- Your estimate in line 2 must be a specific number
- Cite verifiable facts only — no vague patterns
- No hashtags, emojis, exclamation marks
- Return ONLY the tweet text plus your estimate in this format:
  TWEET:
  [tweet text]
  ARKE_PCT: [your probability as integer 0-100]"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            # gpt-oss-120b spends its first few hundred tokens on hidden
            # reasoning; too small a budget truncates the tweet. Give room.
            max_tokens=2048,
        )
        raw = (response.choices[0].message.content or "").strip()

        # Parse tweet and probability defensively. The model sometimes emits
        # "ARKE_PCT:" but stops before the number, so never index blindly.
        arke_pct = market_pct  # default to market if no estimate found

        mpct = re.search(r"ARKE_PCT:\s*(\d{1,3})", raw)
        if mpct:
            arke_pct = max(0, min(100, int(mpct.group(1))))

        # Tweet = text after "TWEET:" (if present) and before "ARKE_PCT:".
        tweet = raw.split("TWEET:", 1)[1] if "TWEET:" in raw else raw
        tweet = re.split(r"ARKE_PCT:", tweet)[0].strip()

        # Fallback: no explicit ARKE_PCT number — pull "Arke estimates X%" from line 2.
        if not mpct:
            lines = tweet.split("\n")
            if len(lines) >= 2:
                nums = re.findall(r'(\d{1,3})\s*%', lines[1])
                if nums:
                    arke_pct = max(0, min(100, int(nums[0])))

        log.info(f"[Forecaster] Market={market_pct}% Arke={arke_pct}% Edge={arke_pct-market_pct:+d}pts")
        return tweet, arke_pct

    except Exception as e:
        log.error(f"[Forecaster] Failed: {e}")
        return "", 0
