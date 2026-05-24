"""
agent/integrations/fred.py — FRED macro data grounding.
Active when FRED_API_KEY is set; returns ('', []) otherwise (fail-open).
Guards against FRED's '.' sentinel for missing observations.
"""
import os
import logging
import httpx

log = logging.getLogger(__name__)
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Map keyword fragments → FRED series IDs.
# Keys are checked as substrings of the lowercased market question.
SERIES = {
    "unemployment": "UNRATE",
    "cpi": "CPIAUCSL",
    "inflation": "CPIAUCSL",
    "fed funds": "FEDFUNDS",
    "interest rate": "FEDFUNDS",
    "10-year": "DGS10",
    "treasury": "DGS10",
    "gdp": "GDP",
    "recession": "UNRATE",   # unemployment is the cleaner recession proxy
}


def macro_context(question: str) -> tuple[str, list]:
    """Return (context_str, citations) for macro markets. Fails open to ('', [])."""
    key = os.getenv("FRED_API_KEY")
    if not key:
        return "", []
    q = (question or "").lower()
    matched = [(name, sid) for name, sid in SERIES.items() if name in q]
    # Deduplicate series IDs (e.g. 'cpi' and 'inflation' both map to CPIAUCSL)
    seen_sids, deduped = set(), []
    for name, sid in matched:
        if sid not in seen_sids:
            seen_sids.add(sid)
            deduped.append((name, sid))
    if not deduped:
        return "", []

    blocks, cites = [], []
    try:
        with httpx.Client(timeout=8.0) as c:
            for name, sid in deduped[:2]:
                r = c.get(FRED_BASE, params={
                    "series_id": sid,
                    "api_key": key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                })
                if r.status_code != 200:
                    continue
                obs = r.json().get("observations", [])
                if not obs:
                    continue
                v = obs[0].get("value")
                d = obs[0].get("date")
                # FRED uses "." as a sentinel for missing/unreleased values
                if v in (None, "", "."):
                    continue
                blocks.append(f"FRED {sid} ({name}) = {v} as of {d}.")
                cites.append({
                    "claim": f"FRED {sid}={v} ({d})",
                    "source_url": f"https://fred.stlouisfed.org/series/{sid}",
                    "retrieved_at": d,
                    "content_sha256": "",
                })
    except Exception as e:
        log.debug(f"[FRED] failed: {e}")
        return "", []

    return ("\n".join(blocks), cites) if blocks else ("", [])
