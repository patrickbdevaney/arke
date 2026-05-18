"""
prove_the_loop.py — Arke core proof

Chain:
1. Fetch live Arke feed from Polymarket Gamma API
2. Pick best market — urgency + volume, non-sports, 20-80% probability
3. Check SQLite deduplication — skip if posted within 48 hours
4. Call Groq gpt-oss-120b to generate analytical tweet
5. Post to @arke_ai via OpenTweet API
6. Record to SQLite with builder code attribution

Run:
  python prove_the_loop.py          # dry run — safe, no post, no db write
  python prove_the_loop.py --post   # live post, burns one OpenTweet credit
"""

import httpx
import asyncio
import os
import sys
import time
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------ #
# DB import — graceful fallback if agent/ not in path                 #
# ------------------------------------------------------------------ #
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from agent.db import ArkeDB

    db = ArkeDB()
    DB_AVAILABLE = True
except Exception as e:
    print(f"[WARN] DB unavailable: {e} — running without persistence")
    db = None
    DB_AVAILABLE = False

DRY_RUN = "--post" not in sys.argv

SPORTS_KEYWORDS = [
    "vs.",
    "vs ",
    "O/U",
    "Spread:",
    "Map ",
    "BO3",
    "BO5",
    "Pistons",
    "Cavaliers",
    "Spurs",
    "Lakers",
    "Dodgers",
    "Red Sox",
    "Braves",
    "Angels",
    "Sinner",
    "Medvedev",
    "Aston Villa",
    "Liverpool",
    "Counter-Strike",
    "LoL",
    "Eurovision",
    "FIFA World Cup",
    "Natus Vincere",
    "Scheffler",
    "PGA",
    "Masters",
    "Wimbledon",
    "Celtics",
    "Knicks",
    "Heat",
    "Warriors",
    "Nuggets",
    "Yankees",
    "Mets",
    "Cubs",
    "Padres",
    "Giants",
]

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "arke.live")
BUILDER_CODE = os.getenv("POLY_BUILDER_CODE", "")
BUILDER_ADDR = os.getenv("POLY_BUILDER_ADDRESS", "")


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #


def is_sports(q: str) -> bool:
    return any(kw.lower() in q.lower() for kw in SPORTS_KEYWORDS)


def get_market_url(market: dict) -> str:
    """Correct Polymarket URL via event slug.
    Appends ?ref= builder address for attribution tracking.
    """
    events = market.get("events", [])
    slug = events[0].get("slug", "") if events else market.get("slug", "")
    base = (
        f"polymarket.com/event/{slug}"
        if slug
        else f"polymarket.com/event/{market.get('slug','')}"
    )
    ref = f"?ref={BUILDER_ADDR}" if BUILDER_ADDR else ""
    return f"{base}{ref}"


def infer_arke_position(tweet_text: str) -> str:
    """Parse whether Arke agreed or disagreed with the market for accuracy tracking."""
    lower = tweet_text.lower()
    if "i disagree" in lower:
        return "DISAGREE"
    if "i think" in lower:
        return "AGREE"
    return "NEUTRAL"


# ------------------------------------------------------------------ #
# Feed                                                                 #
# ------------------------------------------------------------------ #


async def fetch_arke_feed() -> list[dict]:
    """Fetch top 100 markets by 24hr volume, filter to actionable set."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "active": "true",
                "limit": 100,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        r.raise_for_status()
        markets = r.json()

    feed = []
    for m in markets:
        vol = float(m.get("volume24hr", 0))
        price = float(m.get("lastTradePrice", 0))
        pct = int(price * 100)
        q = m.get("question", "")

        if vol > 50_000 and 20 <= pct <= 80 and not is_sports(q):
            feed.append(m)

    feed.sort(key=lambda m: float(m.get("volume24hr", 0)), reverse=True)
    return feed


def pick_best_market(feed: list[dict]) -> dict | None:
    """Prefer markets resolving within 30 days (urgency = engagement).
    Skips markets already posted within the 48hr cooldown.
    Falls back to highest volume if nothing resolves soon.
    """
    import datetime

    today = datetime.date.today()

    # First pass: urgent markets not in cooldown
    for m in feed:
        if DB_AVAILABLE and db.already_posted(
            m.get("conditionId", ""), cooldown_hours=48
        ):
            continue
        end_str = m.get("endDateIso", "")
        try:
            end_date = datetime.date.fromisoformat(end_str)
            days_left = (end_date - today).days
            if 0 <= days_left <= 30:
                return m
        except Exception:
            continue

    # Second pass: any market not in cooldown (long-dated)
    for m in feed:
        if DB_AVAILABLE and db.already_posted(
            m.get("conditionId", ""), cooldown_hours=48
        ):
            continue
        return m

    # Final fallback: ignore cooldown (feed may be fully exhausted)
    print("      [WARN] All markets in cooldown — falling back to top market")
    return feed[0] if feed else None


# ------------------------------------------------------------------ #
# Tweet generation                                                     #
# ------------------------------------------------------------------ #


def generate_tweet(market: dict, groq_api_key: str) -> str:
    """Generate analytical tweet via Groq gpt-oss-120b."""
    client = Groq(api_key=groq_api_key)

    price = float(market.get("lastTradePrice", 0.5))
    pct = int(price * 100)
    question = market["question"]
    vol24 = float(market.get("volume24hr", 0))
    end_date = market.get("endDateIso", "")
    market_url = get_market_url(market)

    context = ""
    events = market.get("events", [])
    if events:
        meta = events[0].get("eventMetadata", {})
        context = meta.get("context_description", "")[:400]

    prompt = f"""You are Arke, an autonomous prediction market intelligence agent. You write sharp, analytical tweets that crypto-native traders respect and engage with.

Market: {question}
Current probability: {pct}% YES
24hr volume: ${vol24:,.0f} USDC
Resolves: {end_date}
Context: {context}

TWEET STRUCTURE (follow exactly):
Line 1: State the event and the market's implied probability as a fact. One sentence. End with a period.
Line 2: Your take — agree or disagree — with exactly one specific, data-grounded reason. Start with "I think" or "I disagree —". End with a period.
Line 3: "Bet: {market_url}"

RULES:
- Total length under 240 characters including the URL
- The probability must appear as a specific percentage number
- Your reason must be specific — cite a mechanism, a historical pattern, or a named data point. Never vague generalities
- Slightly contrarian is better than agreeing with consensus
- No hashtags, no exclamation marks, no emojis, no ellipses
- No comma splices — each clause is its own sentence
- Do not start with "Market says" — vary the opening
- Return only the tweet text, nothing else

GOOD EXAMPLES:
"MicroStrategy holds $40B in Bitcoin with zero liquidation pressure. Market prices 55% chance they sell by May 31 — that contradicts every public commitment Saylor has made since 2020.
Bet: polymarket.com/event/microstrategy-sell-any-bitcoin-in-2025"

"Strait of Hormuz at 30% normal traffic by June. Iran has closed it twice before and reopened within weeks under economic pressure. The market is underpricing normalization.
Bet: polymarket.com/event/strait-of-hormuz-traffic-2026"

BAD EXAMPLES (never do these):
"Market says 55% chance MicroStrategy sells Bitcoin by May 31, I disagree, Saylor's long term strategy is unchanged" — comma splice, vague reason
"55% YES on MicroStrategy selling BTC! Interesting market! 🔥" — exclamations, emoji, no take"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=280,
    )

    return response.choices[0].message.content.strip()


# ------------------------------------------------------------------ #
# Posting                                                              #
# ------------------------------------------------------------------ #


async def post_to_opentweet(tweet: str) -> dict:
    """Post via OpenTweet API. Returns response dict or empty on failure."""
    api_key = os.getenv("OPENTWEET_API_KEY")
    if not api_key:
        print("      OPENTWEET_API_KEY not set — skipping post")
        return {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://opentweet.io/api/v1/posts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "text": tweet,
                "publish_now": True,
            },
        )
        print(f"      HTTP {resp.status_code}")
        print(f"      Response: {resp.text[:300]}")
        if resp.status_code in (200, 201):
            return resp.json()
        return {}


# ------------------------------------------------------------------ #
# Main                                                                 #
# ------------------------------------------------------------------ #


async def main(post: bool | None = None):
    """Run the full loop once.

    post=None (default): use --post / DRY_RUN detection from sys.argv
    post=True: force live post
    post=False: force dry run
    """
    dry_run = (not post) if post is not None else DRY_RUN

    run_start = time.time()

    # ── Env check ──────────────────────────────────────────────────
    print("DEBUG: loading env vars...")
    groq_key = os.getenv("GROQ_API_KEY")
    opentweet_key = os.getenv("OPENTWEET_API_KEY")

    print(f"DEBUG: GROQ_API_KEY      = {groq_key[:10] if groq_key else 'NOT SET'}")
    print(
        f"DEBUG: OPENTWEET_API_KEY = {opentweet_key[:10] if opentweet_key else 'NOT SET'}"
    )
    print(
        f"DEBUG: BUILDER_CODE      = {BUILDER_CODE[:16] if BUILDER_CODE else 'NOT SET'}"
    )
    print(
        f"DEBUG: BUILDER_ADDRESS   = {BUILDER_ADDR[:16] if BUILDER_ADDR else 'NOT SET'}"
    )
    print(f"DEBUG: DB_AVAILABLE      = {DB_AVAILABLE}")
    print(f"DEBUG: DRY_RUN           = {dry_run}")
    print()

    if not groq_key:
        print("ERROR: GROQ_API_KEY not set — add to ~/arke/.env")
        if DB_AVAILABLE:
            db.record_run("error", error_message="GROQ_API_KEY not set")
        return

    # ── DB startup stats ───────────────────────────────────────────
    if DB_AVAILABLE:
        db.print_stats()

    # ── 1. Fetch feed ──────────────────────────────────────────────
    print("[1/4] Fetching Arke feed...")
    try:
        feed = await fetch_arke_feed()
    except Exception as e:
        print(f"      ERROR fetching feed: {e}")
        if DB_AVAILABLE:
            db.record_run("error", error_message=f"feed fetch failed: {e}")
        return

    print(f"      Found {len(feed)} actionable markets")
    for m in feed:
        pct = int(float(m.get("lastTradePrice", 0)) * 100)
        vol = float(m.get("volume24hr", 0))
        cid = m.get("conditionId", "")[:12]
        in_cooldown = DB_AVAILABLE and db.already_posted(m.get("conditionId", ""))
        flag = " [cooldown]" if in_cooldown else ""
        print(f"      {pct}% | ${vol:,.0f}/24h | {cid} | {m['question'][:50]}{flag}")

    if DB_AVAILABLE:
        db.record_feed_snapshot(feed)

    # ── 2. Pick market ─────────────────────────────────────────────
    print("\n[2/4] Picking best market...")
    market = pick_best_market(feed)
    if not market:
        print("      No suitable market found")
        if DB_AVAILABLE:
            db.record_run("skipped", error_message="no suitable market")
        return

    pct = int(float(market.get("lastTradePrice", 0)) * 100)
    vol = float(market.get("volume24hr", 0))
    market_url = get_market_url(market)
    cid = market.get("conditionId", "")

    print(f"      Selected: {market['question']}")
    print(f"      {pct}% YES | ${vol:,.0f}/24h | ends {market.get('endDateIso')}")
    print(f"      URL: https://{market_url}")
    print(f"      conditionId: {cid[:20]}...")

    # Record skip for markets that lost out to cooldown
    if DB_AVAILABLE:
        for m in feed:
            if m.get("conditionId") != cid:
                if db.already_posted(m.get("conditionId", "")):
                    db.record_skip(m, "cooldown_48hr")

    # ── 3. Generate tweet ──────────────────────────────────────────
    print("\n[3/4] Generating tweet...")
    try:
        tweet = generate_tweet(market, groq_key)
    except Exception as e:
        print(f"      ERROR generating tweet: {e}")
        if DB_AVAILABLE:
            db.record_run(
                "error",
                error_message=f"generation failed: {e}",
                market_selected=market.get("question", ""),
            )
        return

    if not tweet or len(tweet) < 20:
        print("      ERROR: tweet empty or too short — model may have failed")
        if DB_AVAILABLE:
            db.record_run(
                "error",
                error_message="empty tweet returned",
                market_selected=market.get("question", ""),
            )
        return

    position = infer_arke_position(tweet)

    print(f"\n{'='*60}")
    print("TWEET:")
    print(tweet)
    print(f"{'='*60}")
    print(f"Length: {len(tweet)} chars | Position: {position}")

    # ── 4. Post or dry run ─────────────────────────────────────────
    print("\n[4/4] Posting to OpenTweet...")

    if dry_run:
        print("      DRY RUN — no post sent, no DB write")
        print(f"      Verify URL resolves: https://{market_url}")
        print(f"\n      Run with --post to go live:")
        print(f"      python prove_the_loop.py --post")
        duration_ms = int((time.time() - run_start) * 1000)
        if DB_AVAILABLE:
            db.record_run(
                "dry_run",
                market_selected=market.get("question", ""),
                duration_ms=duration_ms,
            )
        print(f"\nDone. ({duration_ms}ms)")
        return

    # Live post
    if not opentweet_key:
        print("      ERROR: OPENTWEET_API_KEY not set")
        return

    result = await post_to_opentweet(tweet)

    if result:
        posts = result.get("posts", [{}])
        post_id = posts[0].get("id", "unknown") if posts else "unknown"
        x_post_id = posts[0].get("x_post_id", "") if posts else ""
        x_url = f"https://x.com/arke_ai/status/{x_post_id}" if x_post_id else ""

        print(f"      Success: post id {post_id}")
        if x_url:
            print(f"      X URL: {x_url}")

        # ── DB record ─────────────────────────────────────────────
        if DB_AVAILABLE:
            row_id = db.record_post(
                market=market,
                tweet_text=tweet,
                market_url=market_url,
                opentweet_post_id=post_id,
                x_post_url=x_url,
                arke_position=position,
            )
            duration_ms = int((time.time() - run_start) * 1000)
            db.record_run(
                "posted",
                market_selected=market.get("question", ""),
                duration_ms=duration_ms,
            )
            print(f"      DB row: {row_id}")

        print(f"\n      Check @arke_ai on X")

    else:
        print("      Failed — check HTTP status and response above")
        if DB_AVAILABLE:
            db.record_run(
                "error",
                market_selected=market.get("question", ""),
                error_message="opentweet post failed",
            )

    duration_ms = int((time.time() - run_start) * 1000)
    print(f"\nDone. ({duration_ms}ms)")


if __name__ == "__main__":
    asyncio.run(main())
