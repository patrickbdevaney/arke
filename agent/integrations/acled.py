"""
agent/integrations/acled.py — ACLED conflict-event grounding.

Active when ACLED_EMAIL + ACLED_PASSWORD are set; returns ('', []) otherwise.

Token lifecycle (durable for a 6h scheduled loop):
  - Access token valid 24h; refresh token valid 14 days.
  - Tokens cached to .acled_token.json (gitignored) — survives restarts.
  - On each call: uses cached access token if still fresh (within 5 min buffer).
  - When access token nears expiry: mints a new one via the refresh token
    (no password required) → valid for another 24h.
  - Only falls back to full password auth if refresh token is also expired
    (e.g. agent was offline >14 days).
  - On 401 from the API: cache is deleted → next cycle re-auths cleanly.
  - Fails open at every step: any error → ('', []), loop unaffected.
"""
import os
import json
import time
import logging
from pathlib import Path
from datetime import date, timedelta
import httpx

log = logging.getLogger(__name__)

TOKEN_URL = "https://acleddata.com/oauth/token"
READ_URL  = "https://acleddata.com/api/acled/read"
# Cache sits at the repo root, alongside .env. Gitignored (add to .gitignore).
CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".acled_token.json"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
SKEW = 300  # refresh 5 min before expiry

COUNTRIES = [
    "Myanmar", "Iran", "Israel", "Russia", "Ukraine", "China", "Taiwan",
    "Venezuela", "Syria", "Lebanon", "Yemen", "Sudan", "Gaza",
    "North Korea", "Pakistan", "India", "Ethiopia", "Somalia",
]


# ── token cache helpers ────────────────────────────────────────────────────

def _load() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(d))
        try:
            os.chmod(CACHE_PATH, 0o600)
        except Exception:
            pass
    except Exception as e:
        log.debug(f"[ACLED] cache write failed: {e}")


def _store(tok_response: dict) -> dict:
    """Normalise a token response into a cache dict with absolute expiry times."""
    now = time.time()
    cache = {
        "access_token":  tok_response.get("access_token"),
        "refresh_token": tok_response.get("refresh_token"),
        "access_exp":    now + float(tok_response.get("expires_in", 86400)),
        # ACLED issues 14-day refresh tokens; store conservatively
        "refresh_exp":   now + 13 * 86400,
    }
    _save(cache)
    return cache


def _password_auth(email: str, pw: str) -> dict:
    """Full credential auth. Returns token response dict or {} on failure."""
    try:
        r = httpx.post(TOKEN_URL, data={
            "username": email, "password": pw,
            "grant_type": "password", "client_id": "acled",
            "scope": "authenticated",
        }, headers={"User-Agent": UA}, timeout=12.0)
        if r.status_code == 200:
            return r.json()
        log.debug(f"[ACLED] password auth HTTP {r.status_code}")
    except Exception as e:
        log.debug(f"[ACLED] password auth failed: {e}")
    return {}


def _refresh_auth(refresh_token: str) -> dict:
    """Mint a new access token from the refresh token (no password). {} on fail."""
    try:
        r = httpx.post(TOKEN_URL, data={
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "client_id": "acled",
        }, headers={"User-Agent": UA}, timeout=12.0)
        if r.status_code == 200:
            return r.json()
        log.debug(f"[ACLED] refresh HTTP {r.status_code}")
    except Exception as e:
        log.debug(f"[ACLED] refresh failed: {e}")
    return {}


def _get_token() -> str | None:
    """
    Return a valid access token using the cheapest available path:
      1. Cached access token (no network).
      2. Refresh token (one network call, no password).
      3. Full password auth (fallback only).
    Returns None if credentials are not configured (dormant mode).
    """
    email, pw = os.getenv("ACLED_EMAIL"), os.getenv("ACLED_PASSWORD")
    if not email or not pw:
        return None  # dormant

    now = time.time()
    cache = _load()

    # Fast path: cached access token still fresh
    if cache.get("access_token") and now < cache.get("access_exp", 0) - SKEW:
        return cache["access_token"]

    # Refresh token path: mint new access token without password
    if cache.get("refresh_token") and now < cache.get("refresh_exp", 0) - SKEW:
        tok = _refresh_auth(cache["refresh_token"])
        if tok.get("access_token"):
            log.info("[ACLED] access token refreshed via refresh_token")
            new_cache = _store(tok)
            # Preserve the old refresh token if the response didn't include one
            if not tok.get("refresh_token") and cache.get("refresh_token"):
                new_cache["refresh_token"] = cache["refresh_token"]
                _save(new_cache)
            return new_cache["access_token"]

    # Full password auth (only needed on first run or after >13 day gap)
    tok = _password_auth(email, pw)
    if tok.get("access_token"):
        log.info("[ACLED] access token obtained via password auth")
        return _store(tok)["access_token"]

    return None


# ── public API ─────────────────────────────────────────────────────────────

def geo_context(question: str) -> tuple[str, list]:
    """Return 30-day ACLED event count for the country in the question.
    Fails open to ('', []) on any error, missing creds, or no country match."""
    tok = _get_token()
    if not tok:
        return "", []

    q = (question or "").lower()
    country = next((c for c in COUNTRIES if c.lower() in q), None)
    if not country:
        return "", []

    since = (date.today() - timedelta(days=30)).isoformat()
    today = date.today().isoformat()

    try:
        r = httpx.get(READ_URL, params={
            "_format": "json",
            "country": country,
            "event_date": f"{since}|{today}",
            "event_date_where": "BETWEEN",
            "limit": 500,
            "fields": ("event_id_cnty|event_date|event_type"
                       "|country|fatalities"),
        }, headers={
            "Authorization": f"Bearer {tok}",
            "User-Agent": UA,
        }, timeout=15.0)

        if r.status_code == 200:
            rows = r.json().get("data", []) or []
            n_events = len(rows)
            fatalities = sum(int(e.get("fatalities", 0) or 0) for e in rows)
            ctx = (
                f"ACLED: {country} recorded {n_events} conflict/protest "
                f"events ({fatalities} fatalities) in the last 30 days. "
                f"Use as a base-rate anchor for escalation, airspace, "
                f"ceasefire, and sanctions questions."
            )
            return ctx, [{
                "claim": (f"ACLED {country}: {n_events} events, "
                          f"{fatalities} fatalities (30d)"),
                "source_url": "https://acleddata.com/",
                "retrieved_at": since,
                "content_sha256": "",
            }]

        if r.status_code == 401:
            # Token was revoked or expired mid-cycle — clear cache for next run
            log.warning("[ACLED] 401 — clearing token cache")
            try:
                CACHE_PATH.unlink(missing_ok=True)
            except Exception:
                pass

    except Exception as e:
        log.debug(f"[ACLED] read failed: {e}")

    return "", []
