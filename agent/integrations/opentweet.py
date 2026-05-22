"""
agent/integrations/opentweet.py — Direct X API posting via tweepy

Replaces OpenTweet with direct X API v2 using OAuth 1.0a.
Four credentials required in .env:
  X_API_KEY            — Consumer Key
  X_API_SECRET         — Consumer Secret
  X_ACCESS_TOKEN       — Access Token (for @arke_ai)
  X_ACCESS_TOKEN_SECRET — Access Token Secret

No token expiry. No refresh needed. Posts immediately.

Provides:
  post_tweet(tweet: str) -> dict
  remaining_credits() -> int
"""

import os
import logging
import tweepy

log = logging.getLogger(__name__)


def _cred(*names: str) -> str | None:
    """Return the first non-empty env var among names.

    This deployment's .env names the OAuth 1.0a consumer credentials
    X_API_CONSUMER_KEY / X_API_SECRET_KEY. The spec's canonical names are
    X_API_KEY / X_API_SECRET. Accept either, preferring the canonical name.
    """
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


def _consumer_key() -> str | None:
    return _cred("X_API_KEY", "X_API_CONSUMER_KEY")


def _consumer_secret() -> str | None:
    return _cred("X_API_SECRET", "X_API_SECRET_KEY")


def _get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=_consumer_key(),
        consumer_secret=_consumer_secret(),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
    )


async def post_tweet(tweet: str) -> dict:
    """Post tweet via X API v2. Returns response dict or empty on failure."""
    api_key = _consumer_key()
    if not api_key:
        log.warning("[X] consumer key not set (X_API_KEY / X_API_CONSUMER_KEY) — skipping post")
        return {}

    try:
        client = _get_client()
        response = client.create_tweet(text=tweet)
        tweet_id = response.data["id"]
        x_url = f"https://x.com/arke_ai/status/{tweet_id}"
        log.info(f"[X] Posted successfully: {x_url}")
        return {
            "posts": [{
                "id": tweet_id,
                "x_post_id": tweet_id,
                "x_url": x_url,
                "status": "posted",
            }]
        }
    except tweepy.errors.Forbidden as e:
        log.error(f"[X] Forbidden — check app permissions are Read+Write: {e}")
        return {}
    except tweepy.errors.Unauthorized as e:
        log.error(f"[X] Unauthorized — check credentials in .env: {e}")
        return {}
    except Exception as e:
        log.error(f"[X] Post failed: {e}")
        return {}


async def remaining_credits() -> int:
    """Always returns 99 — X API pay-per-use has no daily limit concept."""
    return 99
