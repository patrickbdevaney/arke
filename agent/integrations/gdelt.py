"""
agent/integrations/gdelt.py — GDELT global news signal source

No API key required. Public REST API.
Base URL: https://api.gdeltproject.org/api/v2/

Provides:
  fetch_trending_topics() -> list[str]         — trending global news keywords
  fetch_geopolitical_events() -> list[dict]    — recent high-coverage events
"""

import re
import logging

import httpx

logger = logging.getLogger(__name__)

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
SUMMARY_URL = "https://api.gdeltproject.org/api/v2/summary/summary"
TV_URL = "https://api.gdeltproject.org/api/v2/tv/search"

TIMEOUT = 5.0


def _extract_keywords(titles: list[str]) -> list[str]:
    seen = set()
    out = []
    for title in titles:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", title or ""):
            w = word.lower()
            if w in seen:
                continue
            seen.add(w)
            out.append(w)
    return out


async def fetch_trending_topics() -> list[str]:
    """Trending global keywords. Returns empty list on any failure (GDELT can be slow)."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                SUMMARY_URL,
                params={"d": "web", "t": "summary"},
            )
            if r.status_code == 200:
                titles = re.findall(r"<title[^>]*>([^<]+)</title>", r.text)
                kws = _extract_keywords(titles)
                if kws:
                    logger.info(f"[GDELT] {len(kws)} trending topics (summary)")
                    return kws
    except Exception as e:
        logger.warning(f"[GDELT] summary endpoint failed: {e}")

    # Fallback: TV search timeline
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                TV_URL,
                params={"query": "politics", "mode": "timelinevol", "format": "json"},
            )
            if r.status_code == 200:
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                titles = [str(v) for v in (data.values() if isinstance(data, dict) else [])]
                kws = _extract_keywords(titles)
                logger.info(f"[GDELT] {len(kws)} trending topics (tv fallback)")
                return kws
    except Exception as e:
        logger.warning(f"[GDELT] tv fallback failed: {e}")

    return []


async def fetch_geopolitical_events(hours_back: int = 6) -> list[dict]:
    """Recent geopolitical news articles. Empty list on any exception."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                DOC_URL,
                params={
                    "query": "geopolitics",
                    "mode": "ArtList",
                    "maxrecords": 10,
                    "format": "json",
                    "timespan": f"{hours_back}h",
                },
            )
            if r.status_code != 200:
                logger.warning(f"[GDELT] doc HTTP {r.status_code}")
                return []
            data = r.json() if r.headers.get("content-type", "").lower().startswith("application/json") else {}
            articles = data.get("articles", []) or []
            out = []
            for a in articles[:10]:
                out.append({
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "datetime": a.get("seendate", ""),
                })
            logger.info(f"[GDELT] {len(out)} geopolitical events fetched")
            return out
    except Exception as e:
        logger.warning(f"[GDELT] fetch_geopolitical_events failed: {e}")
        return []
