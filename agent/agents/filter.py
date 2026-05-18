"""
agent/agents/filter.py — Quality filter via Gemini 2.5 Flash

Free tier from Google AI Studio — no credit card, no expiration.
Uses Google Search grounding to verify factual claims in tweets.
Get key: aistudio.google.com → Get API key

Provides:
  quality_check(tweet: str, market: dict) -> tuple[float, bool, str]
    Returns: (score 0-1, passed bool, reason string)
"""

import os
import json
import re
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/gemini-2.5-flash:generateContent"
)
THRESHOLD = 0.65


def quality_check(tweet: str, market: dict) -> tuple[float, bool, str]:
    """Score tweet quality via Gemini 2.5 Flash. Fail-open on any error."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.warning("[Filter] GEMINI_API_KEY not set — fail-open (0.8)")
        return 0.8, True, "filter_skipped_no_key"

    question = market.get("question", "")
    pct = int(float(market.get("lastTradePrice", 0.5) or 0.5) * 100)
    vol24 = float(market.get("volume24hr", 0) or 0)

    prompt = f"""You are a strict fact-checker for prediction market tweets.

Tweet to evaluate:
{tweet}

Market context: {question} — {pct}% YES probability, ${vol24:,.0f} daily volume

Score on three dimensions (0.0 to 1.0 each):
1. factual: Are specific claims verifiable? If a specific number, date, or event is cited, can you verify it from your knowledge? Score 0.1-0.2 for claims you cannot verify.
2. specific: Does line 2 cite a named mechanism, historical event, specific date, or real data point? Generic phrases like "historical patterns" or "market dynamics" score 0.2.
3. credible: Would a sophisticated prediction market trader find this analytical take credible and worth engaging with?

Critical rule: "I think this is low/high given historical patterns" scores 0.2 on specificity. Real specificity looks like "Iran closed its airspace 3 times in 2023" or "Saylor has publicly committed to never selling since 2020".

Return ONLY valid JSON, nothing else:
{{"score": 0.0, "factual": 0.0, "specific": 0.0, "credible": 0.0, "reason": "one sentence explaining the weakest element"}}"""

    try:
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                # 2.5 Flash burns "thinking" tokens against this budget; disable
                # thinking and use JSON mode so the full structured response fits.
                "maxOutputTokens": 1024,
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 0},
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{GEMINI_URL}?key={api_key}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Strip markdown code fences (Gemini commonly wraps JSON in ```json ... ```)
        fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```\s*$", text)
        if fence:
            text = fence.group(1).strip()

        result = None
        try:
            result = json.loads(text)
        except Exception:
            # Greedy match — captures full JSON even if reason contains nested braces
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    result = json.loads(m.group(0))
                except Exception:
                    result = None

        if result is None:
            log.warning(f"[Filter] no JSON in response: {text[:200]} — fail-open")
            return 0.75, True, "filter_unparseable"
        factual  = float(result.get("factual",  0.0) or 0.0)
        specific = float(result.get("specific", 0.0) or 0.0)
        credible = float(result.get("credible", 0.0) or 0.0)
        score    = (factual * 0.5) + (specific * 0.25) + (credible * 0.25)
        passed   = score >= THRESHOLD
        reason   = str(result.get("reason", ""))[:240]

        log.info(
            f"[Filter] score={score:.2f} factual={factual:.1f} "
            f"specific={specific:.1f} credible={credible:.1f} "
            f"passed={passed} | {reason}"
        )
        return score, passed, reason

    except urllib.error.HTTPError as e:
        log.warning(f"[Filter] Gemini HTTP {e.code}: {e.read()[:100]} — fail-open")
        return 0.75, True, f"filter_http_{e.code}"
    except Exception as e:
        log.warning(f"[Filter] Gemini failed: {e} — fail-open")
        return 0.75, True, f"filter_error: {str(e)[:60]}"
