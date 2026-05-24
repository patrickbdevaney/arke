"""
agent/baserates.py — principled reference-class lookup.

Design:
  - classify_reference_class(question) uses a cheap LLM call to map the
    market question to a reference class by semantics, not keyword matching.
    Falls back to keyword matching if the LLM call fails (fail-open).
  - REFERENCE_CLASSES is the canonical registry. Each entry has:
      id          — stable string identifier
      label       — human-readable class name
      keywords    — fallback keyword list for the no-LLM path
      confidence  — "measured" | "prior" | "redirect"
                    measured  = real counted historical frequency, citable
                    prior     = directional low prior, no clean dataset
                    redirect  = no base rate; use named live_signal instead
      value_pct   — int (None for redirect entries)
      description — what the number means and its limitations
      source_url  — canonical citable source
      live_signal — which live module to prefer over this base rate (or None)
  - get_base_rate(question) → dict | None
    Returns the matched entry or None. The [2.6] wiring in prove_the_loop.py
    uses the confidence field to phrase the forecaster instruction correctly.
"""
import os
import logging

log = logging.getLogger(__name__)

# ── Reference class registry ────────────────────────────────────────────────
# ONLY include entries where confidence="measured" has a real counted dataset.
# confidence="prior" entries exist only where a directional anchor genuinely
# helps and the description honestly states the limitation.
# confidence="redirect" entries exist to route the forecaster to a better signal.

REFERENCE_CLASSES = [
    # ── MEASURED: real counted historical frequencies ───────────────────────
    {
        "id": "incumbent-president-reelection",
        "label": "US incumbent president seeking re-election",
        "keywords": ["incumbent", "re-elect", "reelect", "reelection",
                     "re-election", "second term", "win reelection"],
        "confidence": "measured",
        "value_pct": 74,
        "description": (
            "US incumbent presidents have won re-election in 14 of 19 attempts "
            "since 1900 (74%). Post-WWII the incumbent has ALWAYS won absent a "
            "recession in the election year. Condition on current economic "
            "indicators — with a recession the rate collapses below 50%; "
            "without one it is well above 74%."
        ),
        "source_url": (
            "https://www.goldmansachs.com/insights/articles/"
            "us-president-incumbents-tend-to-win-elections-except-during-recessions"
        ),
        "live_signal": None,
    },
    {
        "id": "congressional-incumbent-reelection",
        "label": "US congressional incumbent seeking re-election",
        "keywords": ["senate seat", "house seat", "congress", "representative",
                     "senator", "incumbents win", "incumbents lose"],
        "confidence": "measured",
        "value_pct": 92,
        "description": (
            "US congressional incumbents win re-election ~90-96% of the time "
            "(House ~96%, cross-chamber average ~92%). Adjust down for open/"
            "contested/wave-election conditions."
        ),
        "source_url": (
            "https://ballotpedia.org/"
            "Election_results,_2024:_Incumbent_win_rates_by_state"
        ),
        "live_signal": None,
    },
    {
        "id": "btc-monthly-direction",
        "label": "Bitcoin closes a calendar month up vs down",
        "keywords": ["bitcoin end the month", "btc end the month",
                     "bitcoin monthly", "btc monthly",
                     "bitcoin close above", "btc close above",
                     "bitcoin this month up", "btc this month up"],
        "confidence": "measured",
        "value_pct": 57,
        "description": (
            "Bitcoin has closed a calendar month UP in roughly 55-60% of months "
            "historically. Varies by month (September is net-negative ~60% of "
            "years; October/November are bullish). Use only for plain "
            "up/down-this-month questions, NOT for price-threshold questions "
            "('above $X') — those should use the Deribit option-implied "
            "probability instead."
        ),
        "source_url": (
            "https://www.bitcoinmagazinepro.com/"
            "bitcoin-portfolio/monthly-returns-heatmap/"
        ),
        "live_signal": None,
    },

    # ── REDIRECT: no useful base rate — route to the live signal ────────────
    {
        "id": "crypto-price-threshold",
        "label": "Crypto asset above a specific price by a specific date",
        "keywords": ["btc above", "bitcoin above", "eth above",
                     "ethereum above", "btc reach", "bitcoin reach",
                     "btc hit", "bitcoin hit", "solana above", "sol above"],
        "confidence": "redirect",
        "value_pct": None,
        "description": (
            "There is no useful unconditional base rate for 'above $X by date' "
            "questions — the answer depends entirely on spot price, distance to "
            "strike, time to expiry, and implied volatility. Use the Deribit "
            "option-implied probability (call delta ≈ risk-neutral Pr(ITM)) "
            "as the anchor. It is already injected into the DERIBIT block above."
        ),
        "source_url": "https://www.deribit.com/",
        "live_signal": "deribit",
    },
    {
        "id": "fomc-rate-decision",
        "label": "FOMC rate decision at a specific meeting",
        "keywords": ["fed cut", "fed hike", "fomc cut", "fomc hike",
                     "rate cut at", "rate hike at", "fed hold",
                     "interest rate decision", "fed leave rates"],
        "confidence": "redirect",
        "value_pct": None,
        "description": (
            "The share of FOMC meetings ending in no-change vs a cut or hike is "
            "regime-dependent and cannot be stated as a reliable base rate. "
            "Use the CME FedWatch tool (Fed-funds-futures-implied odds) for the "
            "specific meeting. The FRED FEDFUNDS series (injected above if "
            "FRED_API_KEY is set) gives the current rate as context."
        ),
        "source_url": (
            "https://www.cmegroup.com/markets/interest-rates/"
            "cme-fedwatch-tool.html"
        ),
        "live_signal": "fred",
    },

    # ── PRIOR: directional low prior, no clean dataset ──────────────────────
    # These entries exist only because a rough anchor + honest caveat is
    # still better than the LLM inventing a number from training data.
    # The forecaster is instructed to treat these as wide priors only.
    {
        "id": "conflict-escalation-near-term",
        "label": "Armed conflict escalates to a specific threshold by a near-term date",
        "keywords": ["airspace", "full-scale invasion", "nuclear",
                     "ground troops", "military strike", "bombing campaign",
                     "declare war", "invade"],
        "confidence": "prior",
        "value_pct": 12,
        "description": (
            "Specific escalation thresholds by a near-term date have a low base "
            "rate — most crises do not escalate to the named threshold on "
            "schedule. No clean published frequency exists; ~12% is a wide low "
            "prior. Condition heavily on the ACLED event count (injected above "
            "if ACLED_EMAIL is set): high recent fatality counts raise this "
            "materially; a plateau or decline lowers it."
        ),
        "source_url": "https://acleddata.com/",
        "live_signal": "acled",
    },
    {
        "id": "peace-deal-near-term",
        "label": "Formal peace deal, ceasefire, or treaty signed by a near-term date",
        "keywords": ["peace deal", "peace agreement", "ceasefire signed",
                     "permanent ceasefire", "peace treaty", "end the war by",
                     "truce by", "armistice"],
        "confidence": "prior",
        "value_pct": 15,
        "description": (
            "Announced negotiations produce a signed agreement by a specific "
            "near-term date in roughly 10-20% of cases historically — talks "
            "slip, collapse, or produce frameworks without signatures far more "
            "often than they conclude on schedule. ~15% is a wide prior. "
            "Adjust with live evidence: a signed framework or announced "
            "deadline raises this; a breakdown or precondition dispute lowers it."
        ),
        "source_url": "https://ucdp.uu.se/",
        "live_signal": "acled",
    },
]

# ── Classification ──────────────────────────────────────────────────────────

def _keyword_match(question: str) -> dict | None:
    """Fallback: return the first entry whose keywords appear in the question."""
    q = (question or "").lower()
    for entry in REFERENCE_CLASSES:
        if any(kw in q for kw in entry["keywords"]):
            return entry
    return None


def _llm_classify(question: str) -> dict | None:
    """
    Use a cheap fast LLM call to classify the question into a reference class
    by semantics. Falls back to None (caller then tries keyword match).
    Uses llama-3.3-70b via Groq (fast, cheap). Fails open.
    """
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    labels = [e["label"] for e in REFERENCE_CLASSES]
    ids    = [e["id"]    for e in REFERENCE_CLASSES]
    prompt = (
        "You are a forecasting assistant. Classify the following prediction "
        "market question into exactly one of the reference classes below, or "
        "respond with 'none' if none apply.\n\n"
        "Reference classes (respond with the id, nothing else):\n"
        + "\n".join(f"- {i}: {l}" for i, l in zip(ids, labels))
        + f"\n\nQuestion: {question}\n\nRespond with only the id or 'none'."
    )
    try:
        from groq import Groq
        client = Groq(api_key=key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=32,
        )
        raw = (resp.choices[0].message.content or "").strip().lower()
        # Match response against known ids
        for entry in REFERENCE_CLASSES:
            if entry["id"] in raw:
                log.info(f"[BaseRate] LLM classified → {entry['id']}")
                return entry
    except Exception as e:
        log.debug(f"[BaseRate] LLM classify failed: {e}")
    return None


def get_base_rate(question: str) -> dict | None:
    """
    Classify the market question into a reference class and return the entry,
    or None if no class applies. Tries LLM classification first (semantic),
    falls back to keyword matching (syntactic). Fails open.
    """
    entry = _llm_classify(question)
    if entry is None:
        entry = _keyword_match(question)
    return entry


def format_base_rate_block(entry: dict) -> str:
    """Confidence-aware forecaster instruction for a reference-class entry.

    The forecaster handles each tier differently:
      measured → reliable anchor; adjust with specific evidence
      prior    → wide directional anchor; prefer the live domain signal
      redirect → no base-rate number; use the live signal injected above
    """
    if entry["confidence"] == "measured":
        return (
            f"BASE RATE [{entry['id']}] (MEASURED — real historical "
            f"frequency, citable): {entry['description']} "
            f"(~{entry['value_pct']}%). Reliable anchor — "
            f"adjust from it with specific evidence."
        )
    if entry["confidence"] == "prior":
        return (
            f"BASE RATE [{entry['id']}] (ROUGH PRIOR — no clean dataset, "
            f"treat as a wide directional anchor only): "
            f"{entry['description']} (~{entry['value_pct']}%). "
            f"Weight this lightly; prefer the live domain signal "
            f"({entry.get('live_signal', 'ACLED/FRED')} block above)."
        )
    # redirect
    return (
        f"BASE RATE NOTE [{entry['id']}]: {entry['description']} "
        f"Use the live signal already injected above — "
        f"do not assert a base-rate number for this question type."
    )


# Keep match_base_rate as an alias so existing imports don't break.
match_base_rate = get_base_rate
