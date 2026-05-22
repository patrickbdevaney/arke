"""
prove_the_loop.py — Arke core proof

Chain:
1. Fetch live Arke feed from Polymarket Gamma API
2. Pick best market — urgency + volume, non-sports, 20-80% probability
3. Check SQLite deduplication — skip if posted within 48 hours
4. Call Groq gpt-oss-120b to generate analytical tweet
5. Post to @arke_ai via the direct X API (tweepy, OAuth 1.0a)
6. Record to SQLite with builder code attribution

Run:
  python prove_the_loop.py          # dry run — safe, no post, no db write
  python prove_the_loop.py --post   # live post via the direct X API
"""

import httpx
import asyncio
import os
import re
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
    # Additional sports to filter with wider probability range
    "Toulouse", "Marseille", "Lyon", "Monaco",
    "Ligue 1", "Serie A", "Bundesliga", "Eredivisie",
    "Roland Garros", "Wimbledon", "US Open", "Australian Open",
    "Tour de France", "Superbowl", "Super Bowl",
    "World Series", "Stanley Cup", "NBA Finals",
    "cricket", "rugby", "MLS", "ATP", "WTA",
    "CS2", "CSGO", "Dota 2", "Overwatch", "PUBG",
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


def infer_arke_probability(tweet_text: str, market_pct: int) -> int:
    """Estimate Arke's implied probability from its take.

    If Arke says "I think" (agrees), return market_pct.
    If Arke says "I disagree", return inverse adjustment:
      - If market is >50%: Arke thinks lower, return market_pct - 15
      - If market is <50%: Arke thinks higher, return market_pct + 15
    Clamped to 5-95%.
    """
    lower = tweet_text.lower()
    if "i disagree" in lower:
        if market_pct > 50:
            return max(5, market_pct - 15)
        else:
            return min(95, market_pct + 15)
    # Default: agree with slight adjustment toward certainty
    return market_pct


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

        if vol > 15_000 and 15 <= pct <= 85 and not is_sports(q):
            feed.append(m)

    feed.sort(key=lambda m: float(m.get("volume24hr", 0)), reverse=True)
    return feed


def pick_best_market(feed: list[dict]) -> dict | None:
    """Pick best market with category diversity.

    Priority order:
    1. Urgent (ending in 0-7 days), not in cooldown, highest volume
    2. Medium term (7-30 days), not in cooldown, highest volume
    3. Any market not in cooldown
    4. Final fallback: top market regardless of cooldown (with warning)
    """
    import datetime
    today = datetime.date.today()

    def in_cooldown(m: dict) -> bool:
        if not DB_AVAILABLE:
            return False
        try:
            return db.already_posted(m.get("conditionId", ""), cooldown_hours=48)
        except Exception:
            return False

    def days_left(m: dict) -> int:
        try:
            end = datetime.date.fromisoformat(
                m.get("endDateIso", "").split("T")[0]
            )
            return (end - today).days
        except Exception:
            return 999

    # Pass 1: urgent, not in cooldown
    urgent = [m for m in feed if not in_cooldown(m) and 0 <= days_left(m) <= 7]
    if urgent:
        selected = urgent[0]
        print(f"      [urgent {days_left(selected)}d] {selected.get('question','')[:60]}")
        return selected

    # Pass 2: medium term, not in cooldown
    medium = [m for m in feed if not in_cooldown(m) and 7 < days_left(m) <= 30]
    if medium:
        selected = medium[0]
        print(f"      [medium {days_left(selected)}d] {selected.get('question','')[:60]}")
        return selected

    # Pass 3: any not in cooldown (long-dated)
    available = [m for m in feed if not in_cooldown(m)]
    if available:
        selected = available[0]
        print(f"      [long-dated] {selected.get('question','')[:60]}")
        return selected

    # Final fallback: ignore cooldown entirely
    print("      [WARN] All markets in cooldown — falling back to top market")
    return feed[0] if feed else None


# ------------------------------------------------------------------ #
# Tweet generation                                                     #
# ------------------------------------------------------------------ #


def generate_tweet(market: dict, groq_client, news_context: str = "") -> str:
    """Generate analytical tweet via Groq using the shared groq_client."""
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

    news_block = ""
    if news_context:
        news_block = f"""

CURRENT SITUATION (background only — do NOT cite this directly):
{news_context[:400]}

Use this to understand the present moment. Your line-2 fact must be a
VERIFIABLE HISTORICAL event, established pattern, or institutional record
that a fact-checker can confirm from public record — NOT this breaking
news, which is too recent to verify."""

    prompt = f"""You are Arke, an autonomous prediction market intelligence agent.
Write a sharp analytical tweet that crypto-native traders respect.

Market: {question}
Probability: {pct}% YES
Volume: ${vol24:,.0f} USDC/24h
Resolves: {end_date}
Context: {context}{news_block}

TWEET STRUCTURE (3 lines, follow exactly):
Line 1: State the market and probability as fact. One sentence. End with period.
Line 2: Your take starting with "I think" or "I disagree —". MUST cite ONE
        specific verifiable fact: a named event, year, organization, or number.
        NOT vague phrases like "historical patterns" or "market dynamics".
Line 3: "Bet: {market_url}"

SPECIFICITY RULES — your take will be rejected if it is vague:
GOOD: "Iran closed its airspace for 72 hours in April 2019 before IATA pressure forced reopening."
GOOD: "The Fed has paused rates at 8 of the last 9 meetings since March 2023."
GOOD: "MicroStrategy's 10-K filed February 2024 showed a 20% increase in BTC holdings."
BAD: "historical patterns suggest this is unlikely"
BAD: "market dynamics indicate underpricing"
BAD: "this seems too high given recent events"

TWEET RULES:
- Under 240 characters total including URL
- Specific percentage number must appear in line 1
- No hashtags, exclamation marks, emojis, ellipses
- No comma splices — each clause its own sentence
- Do not start with "Market says"
- Return only the 3-line tweet, nothing else"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=280,
    )

    return (response.choices[0].message.content or "").strip()


# ------------------------------------------------------------------ #
# Posting                                                              #
# ------------------------------------------------------------------ #


async def post_to_x(tweet: str) -> dict:
    """Post via the direct X API (tweepy) — see agent/integrations/opentweet.py.

    Returns the post-response dict (OpenTweet-compatible {"posts": [...]}) or
    an empty dict on failure.
    """
    from agent.integrations.opentweet import post_tweet

    result = await post_tweet(tweet)
    if result:
        posts = result.get("posts", [{}])
        x_url = posts[0].get("x_url", "") if posts else ""
        print(f"      X API post accepted{(' — ' + x_url) if x_url else ''}")
    else:
        print("      X API post failed — see [X] log lines above for the reason")
    return result


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
    x_consumer = os.getenv("X_API_KEY") or os.getenv("X_API_CONSUMER_KEY")

    print(f"DEBUG: GROQ_API_KEY      = {groq_key[:10] if groq_key else 'NOT SET'}")
    print(f"DEBUG: X_API consumer    = {'SET' if x_consumer else 'NOT SET'}")
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

    # ── 2.5. Fetch signal context ──────────────────────────────────
    print("\n[2.5/4] Fetching signal context...")
    news_context = ""
    try:
        from agent.integrations.signals import fetch_headlines
        headlines = await fetch_headlines()

        if headlines:
            question = market.get("question", "").lower()

            # Extract key entities: tokens >=4 chars, not pure digits, not stopwords.
            # >=4 (not >4) so 4-letter entities like "iran"/"gaza" match — the
            # critical fix for geopolitics markets that the >4 rule silently dropped.
            STOPWORDS = {"will", "what", "when", "does", "have", "this",
                         "that", "with", "from", "they", "their", "been",
                         "than", "into", "more", "also", "some", "such",
                         "over", "most", "many", "year", "next", "week",
                         "days", "time", "like", "just", "only"}
            question_words = [
                w for w in re.findall(r"[a-z0-9]+", question)
                if len(w) >= 4 and not w.isdigit() and w not in STOPWORDS
            ]

            relevant = []
            for h in headlines:
                title_lower = h.get("title", "").lower()
                # Match if ANY single key word from question appears in headline
                if any(w in title_lower for w in question_words):
                    relevant.append(h["title"])

            news_context = " | ".join(relevant[:4])
            if news_context:
                print(f"      Signal context ({len(relevant)} matches): {news_context[:120]}...")
            else:
                print(f"      No signal match in {len(headlines)} headlines — generating without context")
        else:
            print("      No headlines fetched — generating without context")

    except Exception as e:
        print(f"      Signal fetch failed: {e} — continuing without context")

    # Groq client — shared by tweet generation and the quality-filter retry loop
    groq_client = Groq(api_key=groq_key)

    # ── 3. Generate tweet ──────────────────────────────────────────
    print("\n[3/4] Generating tweet...")
    try:
        tweet = generate_tweet(market, groq_client, news_context=news_context)
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
    arke_prob = infer_arke_probability(tweet, pct)

    print(f"\n{'='*60}")
    print("TWEET:")
    print(tweet)
    print(f"{'='*60}")
    print(
        f"Length: {len(tweet)} chars | Position: {position} | "
        f"Market: {pct}% | Arke: {arke_prob}% | Edge: {arke_prob - pct:+d}pts"
    )

    # ── 3.5. Quality filter ────────────────────────────────────────
    print("\n[3.5/4] Quality filter...")
    filter_score = 0.8
    filter_passed = True
    filter_reason = "filter_not_run"
    MAX_FILTER_RETRIES = 2

    for attempt in range(MAX_FILTER_RETRIES + 1):
        try:
            from agent.agents.filter import quality_check
            filter_score, filter_passed, filter_reason = quality_check(tweet, market)
            print(f"      Attempt {attempt+1}: score={filter_score:.2f} passed={filter_passed}")
            if filter_passed:
                break
            print(f"      Blocked: {filter_reason}")
            if attempt < MAX_FILTER_RETRIES:
                print(f"      Retrying with enriched prompt...")
                # Retry with a more prescriptive prompt
                enriched_prompt = f"""Previous take was rejected for being too vague: {filter_reason}

Rewrite this take citing a VERIFIABLE HISTORICAL fact — a named past event
with a year, or an institutional record a fact-checker can confirm from
public record. Do NOT cite recent breaking news (too recent to verify).

Market: {market.get('question', '')}
Probability: {pct}% YES
Resolves: {market.get('endDateIso', '')}
{f'Background (do not cite directly): {news_context[:200]}' if news_context else ''}

REQUIREMENTS:
- Line 1: state market + probability as fact
- Line 2: start with "I think" or "I disagree —" + cite a specific past
  event, year, or named institution that can be independently verified.
- Line 3: "Bet: {market_url}"
- Under 240 chars total
- No vague phrases. Specific verifiable facts only.
- Return only the 3-line tweet."""

                retry_response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": enriched_prompt}],
                    temperature=0.5,
                    max_tokens=280,
                )
                tweet = (retry_response.choices[0].message.content or "").strip()
                position = infer_arke_position(tweet)
                print(f"      Retry tweet: {tweet[:100]}...")
        except Exception as e:
            print(f"      Filter error: {e} — fail-open")
            filter_passed = True
            break

    if not filter_passed:
        print(f"      BLOCKED after {MAX_FILTER_RETRIES+1} attempts — skipping post")
        if DB_AVAILABLE:
            db.record_run(
                "skipped",
                market_selected=market.get("question", ""),
                error_message=f"quality_filter_blocked: {filter_reason}",
            )
        print(f"\nDone.")
        return

    # ── 4. Post or dry run ─────────────────────────────────────────
    print("\n[4/4] Posting to X...")

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
    if not (os.getenv("X_API_KEY") or os.getenv("X_API_CONSUMER_KEY")):
        print("      ERROR: X API consumer key not set (X_API_KEY / X_API_CONSUMER_KEY)")
        return

    result = await post_to_x(tweet)

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
                quality_score=filter_score,
                quality_passed=filter_passed,
                arke_probability_pct=arke_prob,
                news_context=news_context,
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
