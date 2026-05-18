"""
agent/integrations/cryptopanic.py — CryptoPanic news signal source

Free tier: https://cryptopanic.com/api/free/v1/posts/
Requires CRYPTOPANIC_API_KEY env var.

Provides:
  fetch_signals() -> list[str]                  — trending keywords from hot news
  fetch_news(limit=20) -> list[dict]            — raw news items
  match_news_to_market(news, market) -> float   — relevance score 0-1
"""

import os
import re
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_URL = "https://cryptopanic.com/api/free/v1/posts/"

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "to", "for", "on", "at", "by", "with", "from", "as",
    "and", "or", "but", "not", "no", "yes", "if", "then", "this", "that",
    "these", "those", "it", "its", "he", "she", "we", "you", "they",
    "his", "her", "their", "our", "your", "my", "me", "us", "him", "them",
    "will", "would", "could", "should", "can", "may", "might", "must",
    "have", "has", "had", "do", "does", "did", "done",
    "than", "so", "such", "into", "out", "up", "down", "over", "under",
    "more", "most", "less", "least", "all", "any", "some", "few", "many",
    "after", "before", "during", "while", "when", "where", "what", "why",
    "how", "who", "whom", "whose", "which",
}


def _extract_keywords(titles: list[str]) -> list[str]:
    seen = set()
    out = []
    for title in titles:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", title or ""):
            w = word.lower()
            if w in STOPWORDS or len(w) < 3:
                continue
            if w in seen:
                continue
            seen.add(w)
            out.append(w)
    return out


async def fetch_signals(filter: str = "hot", limit: int = 20) -> list[str]:
    """Trending keywords from CryptoPanic hot news. Empty list on any failure."""
    api_key = os.getenv("CRYPTOPANIC_API_KEY")
    if not api_key:
        logger.warning("[CryptoPanic] CRYPTOPANIC_API_KEY not set")
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                API_URL,
                params={
                    "auth_token": api_key,
                    "filter": filter,
                    "kind": "news",
                },
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results", []) or []
            titles = [it.get("title", "") for it in results[:limit]]
            keywords = _extract_keywords(titles)
            logger.info(f"[CryptoPanic] {len(keywords)} signals from {len(titles)} headlines")
            return keywords
    except Exception as e:
        logger.warning(f"[CryptoPanic] fetch_signals failed: {e}")
        return []


async def fetch_news(limit: int = 20) -> list[dict]:
    """Raw news items: title, url, published_at, votes.bullish/bearish, panic_score."""
    api_key = os.getenv("CRYPTOPANIC_API_KEY")
    if not api_key:
        logger.warning("[CryptoPanic] CRYPTOPANIC_API_KEY not set")
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                API_URL,
                params={
                    "auth_token": api_key,
                    "filter": "hot",
                    "kind": "news",
                },
            )
            r.raise_for_status()
            results = (r.json().get("results", []) or [])[:limit]

        out = []
        for it in results:
            votes = it.get("votes", {}) or {}
            out.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "published_at": it.get("published_at", ""),
                "bullish": int(votes.get("positive", 0) or 0),
                "bearish": int(votes.get("negative", 0) or 0),
                "panic_score": int(votes.get("toxic", 0) or 0),
            })
        return out
    except Exception as e:
        logger.warning(f"[CryptoPanic] fetch_news failed: {e}")
        return []


def match_news_to_market(news_items: list[dict], market: dict) -> float:
    """Fraction of market question words found in news titles. Score 0-1."""
    question = (market.get("question", "") or "").lower()
    q_words = {w for w in re.findall(r"[a-z][a-z0-9]{2,}", question) if w not in STOPWORDS}
    if not q_words:
        return 0.0

    corpus = " ".join((n.get("title", "") or "").lower() for n in news_items)
    if not corpus:
        return 0.0

    matched = sum(1 for w in q_words if w in corpus)
    return matched / len(q_words)
