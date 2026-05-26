"""
agent/integrations/research.py — per-market targeted web search.
Tries Brave (BRAVE_SEARCH_API_KEY, or the BRAVE_API_KEY alias) first, then
Tavily (TAVILY_API_KEY), then ('', []).
Hashes full snippet content for verifiable provenance. Fails open.
"""
import os
import hashlib
import logging
from datetime import datetime, timezone
import httpx

log = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _build_query(market: dict) -> str:
    q = market.get("question", "")
    end = (market.get("endDateIso", "") or "")[:10]
    return f"{q} {end}".strip()


def research_market(market: dict, max_results: int = 5) -> tuple[str, list]:
    """Return (summary_str, citations). Citations hash the full snippet text,
    not just the title. Fails open to ('', []) on any error or missing key."""
    query = _build_query(market)
    now = datetime.now(timezone.utc).isoformat()
    # The live .env stores the key as BRAVE_SEARCH_API_KEY; accept the older
    # BRAVE_API_KEY name too so existing configs/tests keep working.
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
    tavily_key = os.getenv("TAVILY_API_KEY")
    results = []

    try:
        if brave_key:
            with httpx.Client(timeout=10.0) as c:
                r = c.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": max_results},
                    headers={"X-Subscription-Token": brave_key,
                             "Accept": "application/json"},
                )
                if r.status_code == 200:
                    for it in (r.json().get("web", {})
                               .get("results", []))[:max_results]:
                        results.append({
                            "title": it.get("title", ""),
                            "url": it.get("url", ""),
                            "snippet": it.get("description", ""),
                        })

        if not results and tavily_key:
            with httpx.Client(timeout=12.0) as c:
                r = c.post(
                    "https://api.tavily.com/search",
                    json={"api_key": tavily_key, "query": query,
                          "max_results": max_results,
                          "search_depth": "basic"},
                )
                if r.status_code == 200:
                    for it in r.json().get("results", [])[:max_results]:
                        results.append({
                            "title": it.get("title", ""),
                            "url": it.get("url", ""),
                            "snippet": it.get("content", ""),
                        })
    except Exception as e:
        log.debug(f"[Research] search failed: {e}")
        return "", []

    if not results:
        return "", []

    citations = [
        {
            "claim": r["title"],
            "source_url": r["url"],
            "retrieved_at": now,
            "content_sha256": _sha256(r["snippet"] or r["title"]),
            "snippet": (r["snippet"] or "")[:500],
        }
        for r in results if r.get("url")
    ]
    summary = "\n".join(
        f"- {r['title']}: {r['snippet'][:160]}" for r in results
    )
    log.info(f"[Research] {len(citations)} results for '{query[:60]}'")
    return summary, citations
