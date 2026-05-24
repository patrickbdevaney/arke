"""
agent/integrations/polymarket.py — Polymarket Gamma API integration

Provides:
  fetch_arke_feed() -> list[dict]   — top non-sports markets with genuine uncertainty
  pick_best_market(feed) -> dict    — urgency-weighted selection with dedup
  get_market_url(market) -> str     — correct polymarket.com/event/{slug} URL with ?ref=
  get_event_context(market) -> str  — Polymarket's own AI context for the market
"""

import os
import datetime
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com/markets"

# Per-category re-post cooldowns (hours). Crypto markets move intraday so they
# can resurface daily; geopolitics resolves on a multi-day news cycle so a 4-day
# cooldown avoids spamming the same conflict. Applied by pick_best_market().
CATEGORY_COOLDOWN_HOURS = {
    "crypto":      24,
    "macro":       72,
    "politics":    48,
    "geopolitics": 96,
    "other":       48,
}

SPORTS_KEYWORDS = [
    "vs.", "vs ", "O/U", "Spread:", "Map ", "BO3", "BO5", "BO7",
    "Pistons", "Cavaliers", "Spurs", "Lakers", "Dodgers", "Red Sox",
    "Braves", "Angels", "Sinner", "Medvedev", "Aston Villa", "Liverpool",
    "Counter-Strike", "CS:GO", "CS2", "LoL", "League of Legends",
    "Dota", "Valorant", "Eurovision", "FIFA World Cup", "FIFA",
    "Natus Vincere", "Scheffler", "PGA", "Masters", "Wimbledon",
    "Celtics", "Knicks", "Heat", "Warriors", "Nuggets", "Yankees",
    "Mets", "Cubs", "Padres", "Giants", "NBA", "NFL", "MLB", "NHL",
    "UFC", "Formula 1", "F1 ", "Grand Prix", "Champions League",
    "Premier League", "La Liga", "Bundesliga", "Serie A",
]


def is_sports(q: str) -> bool:
    """Case-insensitive sports keyword check."""
    if not q:
        return False
    q_lower = q.lower()
    return any(kw.lower() in q_lower for kw in SPORTS_KEYWORDS)


def get_market_url(market: dict) -> str:
    """Correct Polymarket URL via event slug, with builder ?ref= if configured."""
    events = market.get("events", []) or []
    slug = events[0].get("slug", "") if events else market.get("slug", "")
    if not slug:
        slug = market.get("slug", "")
    base = f"polymarket.com/event/{slug}"
    builder_addr = os.getenv("POLY_BUILDER_ADDRESS", "")
    if builder_addr:
        return f"{base}?ref={builder_addr}"
    return base


def get_event_context(market: dict) -> str:
    """Extract Polymarket's own AI context_description, truncated to 400 chars."""
    events = market.get("events", []) or []
    if not events:
        return ""
    meta = events[0].get("eventMetadata", {}) or {}
    return (meta.get("context_description", "") or "")[:400]


async def fetch_arke_feed() -> list[dict]:
    """Fetch top markets by 24hr volume; filter to actionable set.

    Pulls 500 markets (was 100) and widens the probability band to 5–95% (was
    15–85%) so tail markets — where Arke's edge vs the crowd is largest — are in
    scope. Quality filters are tightened to compensate:

      * vol > 10_000 (was 15k). Polymarket's reported 24h volume roughly
        double-counts maker+taker legs (see Paradigm's Dec 2025 liquidity
        analysis) and a slice is wash/incentive churn, so the effective real
        flow at the old 15k bar was already low. Lowering the nominal bar to 10k
        while ADDING the liquidity + spread gates below filters out wash-inflated
        thin books far more reliably than a volume threshold alone.
      * liquidity > 25_000 — a real resting order book, not a single LP.
      * spread < 0.05 — a tight two-sided market, not a stale quote.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                GAMMA_URL,
                params={
                    "active": "true",
                    "limit": 500,
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            r.raise_for_status()
            markets = r.json()
    except Exception as e:
        logger.error(f"[Polymarket] fetch failed: {e}")
        return []

    feed = []
    for m in markets:
        try:
            vol = float(m.get("volume24hr", 0) or 0)
            liquidity = float(m.get("liquidity", 0) or 0)
            spread = float(m.get("spread", 0) or 0)
            price = float(m.get("lastTradePrice", 0) or 0)
            pct = int(price * 100)
            q = m.get("question", "") or ""
        except (TypeError, ValueError):
            continue

        if (
            vol > 10_000
            and liquidity > 25_000
            and spread < 0.05
            and 5 <= pct <= 95
            and not is_sports(q)
        ):
            feed.append(m)

    feed.sort(key=lambda m: float(m.get("volume24hr", 0) or 0), reverse=True)
    logger.info(f"[Polymarket] {len(feed)} actionable markets fetched")
    return feed


def pick_best_market(feed: list[dict], db=None) -> dict | None:
    """Prefer markets resolving in 0-30 days that aren't in cooldown.
    Fallback to any not in cooldown. Final fallback: top market with warning.

    Cooldown is per-category (CATEGORY_COOLDOWN_HOURS): a crypto market can
    resurface after 24h while a geopolitics market is held for 96h. The
    category is derived from the question via agent.db.categorize().
    """
    if not feed:
        return None

    # Local import avoids a circular import (agent.db imports nothing from here,
    # but keeping it lazy mirrors the rest of the codebase's db usage).
    from agent.db import categorize

    today = datetime.date.today()

    def in_cooldown(m: dict) -> bool:
        if db is None:
            return False
        try:
            cat = categorize(m.get("question", ""))
            hours = CATEGORY_COOLDOWN_HOURS.get(cat, 48)
            return db.already_posted(m.get("conditionId", ""), cooldown_hours=hours)
        except Exception:
            return False

    # First pass: urgent (≤30 days) and not in cooldown
    for m in feed:
        if in_cooldown(m):
            continue
        end_str = m.get("endDateIso", "") or ""
        try:
            end_date = datetime.date.fromisoformat(end_str.split("T")[0])
            days_left = (end_date - today).days
            if 0 <= days_left <= 30:
                logger.info(
                    f"[Polymarket] Selected (urgent, {days_left}d left): "
                    f"{m.get('question', '')[:60]}"
                )
                return m
        except Exception:
            continue

    # Second pass: anything not in cooldown
    for m in feed:
        if in_cooldown(m):
            continue
        logger.info(
            f"[Polymarket] Selected (not in cooldown): {m.get('question', '')[:60]}"
        )
        return m

    # Final fallback: ignore cooldown
    logger.warning("[Polymarket] All markets in cooldown — using top market")
    return feed[0]
