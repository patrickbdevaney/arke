"""
agent/agents/filter.py — Quality gate for generated tweets

Uses Groq openai/gpt-oss-120b as the judge model.
Separate model from generator (llama-3.3-70b-versatile) so
rate limits don't interfere — each model has its own 1K RPD bucket.

Scoring:
  factual    0.0-1.0  — does the take cite verifiable facts?
  specific   0.0-1.0  — is the reasoning specific, not vague?
  credible   0.0-1.0  — would a prediction market trader find this credible?
  composite  weighted average, threshold 0.65 to pass

Fail-open: if the API call fails for any reason, returns passed=True
so the pipeline doesn't stall.
"""

import os
import json
import logging
from groq import Groq

log = logging.getLogger(__name__)

JUDGE_MODEL = "openai/gpt-oss-120b"
PASS_THRESHOLD = 0.65


def quality_check(tweet: str, market: dict) -> tuple[float, bool, str]:
    """
    Evaluate tweet quality using Groq judge model.

    Returns:
        (score, passed, reason)
        score: float 0.0-1.0
        passed: bool
        reason: explanation string
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        log.warning("[Filter] GROQ_API_KEY not set — fail open")
        return 0.8, True, "no_api_key_fail_open"

    question = market.get("question", "")
    pct = int(float(market.get("lastTradePrice", 0)) * 100)

    prompt = f"""You are evaluating a prediction market tweet for quality.

Market: {question}
Market probability: {pct}% YES

Tweet to evaluate:
{tweet}

Score this tweet on three dimensions from 0.0 to 1.0:

1. factual: Does line 2 cite a specific verifiable fact?
   A named event, year, organization, or number that can be checked?
   1.0 = specific verifiable fact cited
   0.5 = somewhat specific but could be more precise
   0.0 = vague generality like "historical patterns" or "market dynamics"

2. specific: Is the reasoning precise and testable?
   1.0 = a reader could verify the claim independently
   0.5 = partially specific
   0.0 = completely vague, no way to verify

3. credible: Would an informed prediction market trader find this take credible?
   1.0 = sharp analytical take grounded in evidence
   0.5 = reasonable but not particularly insightful
   0.0 = unsupported, contradictory, or obviously wrong

Respond with ONLY valid JSON, no other text:
{{
  "factual": 0.0,
  "specific": 0.0,
  "credible": 0.0,
  "reason": "one sentence explanation"
}}"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            # gpt-oss-120b is a reasoning model: it spends ~500-600 tokens on
            # hidden reasoning before emitting the JSON. 200 truncates the JSON
            # (finish_reason=length) and the filter fails open. Give it room.
            max_tokens=1024,
        )

        raw = (response.choices[0].message.content or "").strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Model occasionally wraps the JSON in prose — grab the first object.
            import re
            m = re.search(r"\{[\s\S]*\}", raw)
            if not m:
                raise
            data = json.loads(m.group(0))
        factual  = float(data.get("factual",  0.5))
        specific = float(data.get("specific", 0.5))
        credible = float(data.get("credible", 0.5))
        reason   = data.get("reason", "")

        # Weighted composite: factual and specific matter most
        score = (factual * 0.4) + (specific * 0.4) + (credible * 0.2)
        passed = score >= PASS_THRESHOLD

        log.info(
            f"[Filter] score={score:.2f} factual={factual} "
            f"specific={specific} credible={credible} "
            f"passed={passed} | {reason}"
        )
        return score, passed, reason

    except json.JSONDecodeError as e:
        log.warning(f"[Filter] JSON parse failed: {e} — fail open")
        return 0.8, True, f"json_parse_error_fail_open"
    except Exception as e:
        log.warning(f"[Filter] API error: {e} — fail open")
        return 0.8, True, f"api_error_fail_open: {str(e)[:80]}"
