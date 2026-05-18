"""
agent/integrations/opentweet.py — OpenTweet API integration

Provides:
  post_tweet(tweet: str) -> dict   — posts to @arke_ai, returns response
  remaining_credits() -> int       — checks remaining URL post credits
"""

import os
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

POSTS_URL = "https://opentweet.io/api/v1/posts"
ME_URL = "https://opentweet.io/api/v1/me"


async def post_tweet(tweet: str) -> dict:
    """POST tweet to OpenTweet. Returns response JSON on 2xx, else empty dict."""
    api_key = os.getenv("OPENTWEET_API_KEY")
    if not api_key:
        logger.warning("[OpenTweet] OPENTWEET_API_KEY not set — skipping post")
        return {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                POSTS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"text": tweet, "publish_now": True},
            )
            logger.info(f"[OpenTweet] HTTP {resp.status_code}")
            if resp.status_code in (200, 201):
                return resp.json()
            logger.error(f"[OpenTweet] error body: {resp.text[:300]}")
            return {}
    except Exception as e:
        logger.error(f"[OpenTweet] request failed: {e}")
        return {}


async def remaining_credits() -> int:
    """GET /me; return limits.remaining_posts_today, or -1 on failure."""
    api_key = os.getenv("OPENTWEET_API_KEY")
    if not api_key:
        logger.warning("[OpenTweet] OPENTWEET_API_KEY not set")
        return -1

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                ME_URL,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                logger.warning(f"[OpenTweet] /me HTTP {resp.status_code}")
                return -1
            data = resp.json()
            limits = data.get("limits", {}) or {}
            return int(limits.get("remaining_posts_today", -1))
    except Exception as e:
        logger.error(f"[OpenTweet] /me failed: {e}")
        return -1
