"""
agent/agents/forecaster_agent.py — Probability forecaster agent

Takes market data and signal report.
Produces a tweet with a specific Arke probability estimate
that diverges from (or confirms) the market consensus.
The probability estimate is the core product signal.
"""

import os
import re
import hashlib
import logging
from datetime import datetime, timezone
from groq import Groq

log = logging.getLogger(__name__)
MODEL = "openai/gpt-oss-120b"


def _extract_citations(text: str) -> list:
    """Pull inline https?:// URLs out of the tweet as citations. The Bet: line
    (scheme-less polymarket.com/...) is intentionally not matched."""
    now = datetime.now(timezone.utc).isoformat()
    seen, cites = set(), []
    for raw in re.findall(r"https?://\S+", text or ""):
        url = raw.rstrip(").,;'\"")
        if url in seen:
            continue
        seen.add(url)
        cites.append({
            "claim": "",
            "source_url": url,
            "retrieved_at": now,
            "content_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
        })
    return cites


def run_forecaster_agent(
    market: dict,
    signal_report: str,
    market_url: str,
) -> tuple[str, int, list]:
    """
    Generate analytical tweet with specific probability estimate.

    Returns:
        (tweet_text, arke_probability_pct, citations)
        arke_probability_pct: Arke's estimate (may differ from market)
        citations: inline URLs cited in the tweet (provenance)
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "", 0, []

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

EVIDENCE MUST BE DIRECTIONAL (your tweet is rejected otherwise):
GOOD — base rate that directly implies the estimate:
  "Arke estimates 12% — incumbent senators have lost re-election in only 6 of
   the last 84 contested races since 2018 (≈7%)."
BAD — real named event that argues for no specific number (non-sequitur):
  "Arke estimates 70% — the 2015 JCPOA shows diplomacy between these states is
   possible." (The JCPOA is real but does not argue for 70% over 40% or 90%.)
BAD — analogy to an unrelated historical event:
  "Arke estimates 30% — like the 2008 financial crisis, markets can turn fast."
  (2008 says nothing about THIS market's resolution.)

RULES:
- Under 260 characters total
- Your estimate in line 2 must be a specific number
- Cite verifiable facts only — no vague patterns
- The cited fact must DIRECTLY imply your probability estimate direction —
  not merely be related to the topic.
- Never justify an estimate with an analogy to an unrelated historical event.
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
            # gpt-oss-120b spends its hidden-reasoning budget first; with this
            # full prompt that runs ~700–2000+ tokens, so 2048 was exhausted by
            # reasoning before any tweet emitted (finish_reason=length, empty
            # content). 4096 leaves room for the tweet after reasoning.
            max_tokens=4096,
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
        return tweet, arke_pct, _extract_citations(tweet)

    except Exception as e:
        log.error(f"[Forecaster] Failed: {e}")
        return "", 0, []


def run_forecaster_ensemble(
    market: dict,
    signal_report: str,
    market_url: str,
) -> tuple[str, int, list]:
    """
    Run three forecasters in parallel with different model + framing combos.
    Aggregate via MEDIAN of the probability estimates (Schoenegger 2024).
    Falls back to run_forecaster_agent() if fewer than 2 succeed.
    """
    import statistics

    CONFIGS = [
        # (model, framing_label, extra_instruction)
        (
            "openai/gpt-oss-120b",
            "superforecaster",
            "",   # existing prompt — no extra instruction
        ),
        (
            "llama-3.3-70b-versatile",
            "base-rate-first",
            (
                "Lead with the reference class and base rate from the BASE RATE "
                "block (if present). If confidence is MEASURED, treat the "
                "percentage as a reliable anchor and state it explicitly. "
                "If confidence is ROUGH PRIOR, name the class but weight it "
                "lightly and anchor instead on the live domain signal. "
                "If it is a BASE RATE NOTE (redirect), ignore the number and "
                "use the live signal block. Then adjust from the anchor with "
                "the most specific evidence available."
            ),
        ),
        (
            "qwen/qwen3-32b",
            "devil's-advocate",
            (
                "Argue AGAINST the market consensus. Identify the strongest "
                "specific reason the market is wrong, then estimate what the "
                "probability should be. If you genuinely cannot find a flaw, "
                "you may confirm the market, but bias toward disagreement."
            ),
        ),
    ]

    successes: list[tuple[str, int, list]] = []

    for model, label, extra in CONFIGS:
        try:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                continue
            client = Groq(api_key=api_key)
            question   = market.get("question", "")
            market_pct = int(float(market.get("lastTradePrice", 0)) * 100)
            vol        = float(market.get("volume24hr", 0))
            end        = market.get("endDateIso", "")
            sig_block  = (f"\nSIGNAL REPORT:\n{signal_report}"
                          if signal_report else "")
            extra_block = (f"\n\nFRAMING INSTRUCTION:\n{extra}" if extra else "")

            prompt = f"""You are Arke, an autonomous prediction market intelligence agent.
You apply superforecasting methodology: reference class thinking, base rates,
specific mechanisms. You produce calibrated probability estimates.

Market: {question}
Market consensus: {market_pct}% YES
24hr volume: ${vol:,.0f}
Resolves: {end}{sig_block}{extra_block}

Your task:
1. Assess whether the market consensus of {market_pct}% is correct
2. Produce YOUR probability estimate
3. Write a 3-line tweet

TWEET FORMAT (follow exactly):
Line 1: State the market and the market's probability as fact. One sentence.
Line 2: "Arke estimates [X]% — " followed by one specific cited reason.
         X is YOUR probability estimate. The reason MUST cite a specific
         year, named event, or number.
Line 3: "Bet: {market_url}"

RULES:
- Under 260 characters total
- Your estimate in line 2 must be a specific number
- Cite verifiable facts only
- The cited fact must DIRECTLY imply your probability direction
- No hashtags, emojis, exclamation marks
- Return ONLY:
  TWEET:
  [tweet text]
  ARKE_PCT: [your probability as integer 0-100]"""

            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=4096,
            )
            raw = (resp.choices[0].message.content or "").strip()
            arke_pct = market_pct
            mpct = re.search(r"ARKE_PCT:\s*(\d{1,3})", raw)
            if mpct:
                arke_pct = max(0, min(100, int(mpct.group(1))))
            tweet = raw.split("TWEET:", 1)[1] if "TWEET:" in raw else raw
            tweet = re.split(r"ARKE_PCT:", tweet)[0].strip()
            if not mpct:
                lines = tweet.split("\n")
                if len(lines) >= 2:
                    nums = re.findall(r"(\d{1,3})\s*%", lines[1])
                    if nums:
                        arke_pct = max(0, min(100, int(nums[0])))
            log.info(f"[Ensemble:{label}] {model} → {arke_pct}%")
            successes.append((tweet, arke_pct, _extract_citations(tweet)))
        except Exception as e:
            log.warning(f"[Ensemble:{label}] failed: {e}")

    if len(successes) < 2:
        log.warning("[Ensemble] <2 forecasters succeeded — falling back to single")
        return run_forecaster_agent(market, signal_report, market_url)

    pcts   = [s[1] for s in successes]
    median = int(statistics.median(pcts))
    best   = min(successes, key=lambda s: abs(s[1] - median))
    log.info(f"[Ensemble] estimates={pcts} median={median} "
             f"spread={max(pcts)-min(pcts)}pts")

    # Merge + dedup citations by source_url
    seen_urls: set[str] = set()
    merged_cites: list[dict] = []
    for _, _, cites in successes:
        for c in cites:
            url = c.get("source_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                merged_cites.append(c)

    return best[0], median, merged_cites
