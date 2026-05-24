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


def _resolve_token_and_side(market: dict, arke_pct: int) -> tuple[str, str]:
    """Resolve the CLOB token_id and side matching Arke's directional call.

    side = YES when Arke leans >50%, else NO. token_id is the Polymarket
    clobTokenId for that outcome ([0]=YES, [1]=NO). Returns ('', side) when
    the market carries no token ids.
    """
    side = "YES" if arke_pct > 50 else "NO"
    raw = market.get("clobTokenIds")
    tokens = raw
    if isinstance(raw, str):
        import json as _json
        try:
            tokens = _json.loads(raw)
        except Exception:
            tokens = []
    token_id = ""
    if isinstance(tokens, list) and len(tokens) >= 2:
        token_id = tokens[0] if side == "YES" else tokens[1]
    return token_id, side


# ------------------------------------------------------------------ #
# Feed                                                                 #
# ------------------------------------------------------------------ #


async def fetch_arke_feed() -> list[dict]:
    """Fetch top 500 markets by 24hr volume, filter to actionable set.

    Wider coverage: 500 markets and a 5–95% probability band (was 100 / 15–85%)
    surface tail markets where Arke's edge vs the crowd is largest. Tighter
    quality gates compensate: Polymarket's 24h volume roughly double-counts
    maker+taker legs and includes wash/incentive churn (Paradigm, Dec 2025), so
    the nominal volume bar drops to 10k but a real-liquidity gate (>$25k resting
    book) and a tight-spread gate (<5c) are added to screen out wash-inflated
    thin books that a volume threshold alone lets through.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "active": "true",
                "limit": 500,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        r.raise_for_status()
        markets = r.json()

    feed = []
    for m in markets:
        vol = float(m.get("volume24hr", 0) or 0)
        liquidity = float(m.get("liquidity", 0) or 0)
        spread = float(m.get("spread", 0) or 0)
        price = float(m.get("lastTradePrice", 0) or 0)
        pct = int(price * 100)
        q = m.get("question", "")

        if (
            vol > 10_000
            and liquidity > 25_000
            and spread < 0.05
            and 5 <= pct <= 95
            and not is_sports(q)
        ):
            feed.append(m)

    feed.sort(key=lambda m: float(m.get("volume24hr", 0) or 0), reverse=True)
    return feed


def _category_cooldown_hours(question: str) -> int:
    """Per-category re-post cooldown in hours. Mirrors
    agent.integrations.polymarket.CATEGORY_COOLDOWN_HOURS so the live loop and
    the helper module agree on the cadence."""
    from agent.integrations.polymarket import CATEGORY_COOLDOWN_HOURS
    from agent.db import categorize
    return CATEGORY_COOLDOWN_HOURS.get(categorize(question), 48)


def market_in_cooldown(m: dict) -> bool:
    """Category-aware cooldown check used by both pick_best_market and the
    MARKET WATCH fallback detection in main(). Fails open (False) without a DB."""
    if not DB_AVAILABLE:
        return False
    try:
        hours = _category_cooldown_hours(m.get("question", ""))
        return db.already_posted(m.get("conditionId", ""), cooldown_hours=hours)
    except Exception:
        return False


def pick_best_market(feed: list[dict]) -> dict | None:
    """Pick best market with category diversity.

    Priority order:
    1. Urgent (ending in 0-7 days), not in cooldown, highest volume
    2. Medium term (7-30 days), not in cooldown, highest volume
    3. Any market not in cooldown
    4. Final fallback: top market regardless of cooldown (with warning)

    Cooldown is per-category (see CATEGORY_COOLDOWN_HOURS): crypto markets
    resurface after 24h, geopolitics is held 96h.
    """
    import datetime
    today = datetime.date.today()

    def in_cooldown(m: dict) -> bool:
        return market_in_cooldown(m)

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
                if market_in_cooldown(m):
                    db.record_skip(m, "category_cooldown")

    # ── MARKET WATCH detection ─────────────────────────────────────
    # If every actionable market is within its per-category cooldown, then
    # pick_best_market returned the stale top-market fallback. Re-running the
    # full council on a stale market produces a near-duplicate post; instead
    # signal the caller (the scheduler) to post a MARKET WATCH summary. Returns
    # before the council runs so no LLM budget is spent on a stale market.
    all_cooldown = (
        DB_AVAILABLE and bool(feed) and all(market_in_cooldown(m) for m in feed)
    )
    if all_cooldown:
        print("      [MARKET WATCH] all markets in cooldown — skipping council, "
              "signaling watch summary")
        duration_ms = int((time.time() - run_start) * 1000)
        if DB_AVAILABLE:
            db.record_run(
                "skipped",
                market_selected="(all markets in cooldown)",
                error_message="market_watch_fallback",
                duration_ms=duration_ms,
            )
        print(f"\nDone. ({duration_ms}ms)")
        return "all_cooldown"

    # ── 2.5: Signal Agent ─────────────────────────────────────────────
    print("\n[2.5/4] Signal Agent — aggregating context...")
    news_context = ""
    signal_report = ""
    signal_citations = []
    try:
        from agent.integrations.signals import fetch_headlines
        from agent.agents.signal_agent import run_signal_agent

        headlines = await fetch_headlines()
        if headlines:
            # Match headlines to market using key entity words
            question_lower = market.get("question", "").lower()
            STOPWORDS = {"will", "what", "when", "does", "have", "this", "that",
                         "with", "from", "they", "their", "been", "than", "into"}
            q_words = [w for w in question_lower.split()
                       if len(w) > 4 and w not in STOPWORDS]
            matched = [h for h in headlines
                       if any(w in h.get("title", "").lower() for w in q_words)]

            print(f"      {len(headlines)} headlines fetched, {len(matched)} matched")
            if matched:
                news_context = " | ".join(h.get("title", "") for h in matched[:4])
                signal_report, signal_citations = run_signal_agent(market, matched[:8])
                if signal_report:
                    print(f"      Signal report: {signal_report[:100]}...")
            else:
                print("      No headline matches — proceeding without context")
    except Exception as e:
        print(f"      Signal agent failed: {e} — continuing")

    # ── 2.6: Grounded context ──────────────────────────────────────────────
    print("\n[2.6/4] Grounded context — CLOB / search / base rates / domain APIs...")
    grounded_blocks: list[str] = []
    grounded_citations: list[dict] = []
    try:
        from agent.integrations.clob import (get_microstructure,
                                              extract_yes_token_id)
        from agent.integrations.research import research_market
        from agent.baserates import get_base_rate, format_base_rate_block
        from agent.integrations.fred import macro_context
        from agent.integrations.deribit import crypto_context
        from agent.integrations.acled import geo_context

        q_text = market.get("question", "")

        # CLOB microstructure — midpoint is a cleaner anchor than last-trade
        micro = get_microstructure(extract_yes_token_id(market))
        if micro.get("midpoint") is not None:
            mid  = int(micro["midpoint"] * 100)
            last = int(float(market.get("lastTradePrice", 0)) * 100)
            sp   = (micro.get("spread") or 0) * 100
            grounded_blocks.append(
                f"ORDERBOOK: midpoint {mid}% (last-trade {last}%), "
                f"spread {sp:.1f}c. Prefer midpoint as the probability anchor."
            )
            if micro.get("book_hash"):
                grounded_citations.append({
                    "claim": f"CLOB orderbook midpoint {mid}%",
                    "source_url": "https://clob.polymarket.com/book",
                    "retrieved_at": "",
                    "content_sha256": micro["book_hash"],
                })

        # Per-market web search
        rsum, rcites = research_market(market)
        if rsum:
            grounded_blocks.append("RESEARCH:\n" + rsum)
            grounded_citations.extend(rcites)

        # Base rate — confidence-aware phrasing so forecaster knows how much
        # to trust the number (measured vs rough prior vs redirect-to-signal)
        br = get_base_rate(q_text)
        if br:
            grounded_blocks.append(format_base_rate_block(br))
            grounded_citations.append({
                "claim": br["description"],
                "source_url": br["source_url"],
                "retrieved_at": "",
                "content_sha256": "",
            })

        # Domain APIs — each fires only when its key is set AND the market
        # matches; all fail open to ('', [])
        for fn in (macro_context, crypto_context, geo_context):
            try:
                ctx, cites = fn(q_text)
                if ctx:
                    grounded_blocks.append(ctx)
                    grounded_citations.extend(cites)
            except Exception:
                pass

        print(f"      {len(grounded_blocks)} grounded blocks, "
              f"{len(grounded_citations)} citations")

    except Exception as e:
        print(f"      Grounded context failed: {e} — continuing without it")

    # Append grounded blocks to the signal report fed to the Forecaster
    if grounded_blocks:
        signal_report = (
            (signal_report + "\n\n") if signal_report else ""
        ) + "\n\n".join(grounded_blocks)

    # ── 3: Forecaster Agent ───────────────────────────────────────────
    print("\n[3/4] Forecaster Agent — generating probability estimate...")
    from agent.agents.forecaster_agent import run_forecaster_agent

    tweet = ""
    arke_pct = int(float(market.get("lastTradePrice", 0)) * 100)
    forecaster_citations = []

    for attempt in range(3):
        try:
            if os.getenv("ENABLE_ENSEMBLE") == "1":
                from agent.agents.forecaster_agent import run_forecaster_ensemble
                tweet, arke_pct, forecaster_citations = run_forecaster_ensemble(
                    market, signal_report, market_url)
            else:
                tweet, arke_pct, forecaster_citations = run_forecaster_agent(
                    market, signal_report, market_url)
            if tweet and len(tweet) > 20:
                break
            print(f"      Attempt {attempt+1}: empty response — retrying")
        except Exception as e:
            print(f"      Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                if DB_AVAILABLE:
                    db.record_run("error",
                        market_selected=market.get("question", ""),
                        error_message=f"forecaster failed: {e}")
                return

    if not tweet:
        print("      Forecaster produced no tweet — skipping")
        if DB_AVAILABLE:
            db.record_run("error",
                market_selected=market.get("question", ""),
                error_message="forecaster empty tweet")
        return

    market_pct = int(float(market.get("lastTradePrice", 0)) * 100)
    edge = arke_pct - market_pct
    position = "AGREE" if abs(edge) <= 3 else ("BULL" if edge > 0 else "BEAR")

    print(f"\n{'='*60}")
    print("TWEET:")
    print(tweet)
    print(f"{'='*60}")
    print(f"Length: {len(tweet)} | Market: {market_pct}% | Arke: {arke_pct}% | Edge: {edge:+d}pts | {position}")

    # ── 3.5: Adversary Agent + Quality Filter ─────────────────────────
    print("\n[3.5/4] Adversary Agent + Quality Filter...")
    from agent.agents.adversary_agent import run_adversary_agent
    from agent.agents.filter import quality_check

    # Adversary first
    tweet, adversary_passed = run_adversary_agent(tweet, market, market_url)
    print(f"      Adversary: {'PASS' if adversary_passed else 'REWRITE'}")

    # Quality filter with up to 2 retries
    filter_score, filter_passed, filter_reason = 0.8, True, "not_run"
    for attempt in range(3):
        filter_score, filter_passed, filter_reason = quality_check(tweet, market)
        print(f"      Filter attempt {attempt+1}: score={filter_score:.2f} passed={filter_passed}")
        if filter_passed:
            break
        if attempt < 2:
            print(f"      Retrying forecaster with enriched prompt...")
            # Force another forecaster attempt with the rejection reason
            enriched_signal = (signal_report or "") + f"\n\nPREVIOUS ATTEMPT REJECTED: {filter_reason}\nMust cite a more specific verifiable fact."
            if os.getenv("ENABLE_ENSEMBLE") == "1":
                from agent.agents.forecaster_agent import run_forecaster_ensemble
                tweet, arke_pct, forecaster_citations = run_forecaster_ensemble(
                    market, enriched_signal, market_url)
            else:
                tweet, arke_pct, forecaster_citations = run_forecaster_agent(
                    market, enriched_signal, market_url)

    # Recompute edge/position in case a retry changed Arke's estimate
    edge = arke_pct - market_pct
    position = "AGREE" if abs(edge) <= 3 else ("BULL" if edge > 0 else "BEAR")

    if not filter_passed:
        print(f"      BLOCKED after 3 attempts — skipping post")
        if DB_AVAILABLE:
            db.record_run("skipped",
                market_selected=market.get("question", ""),
                error_message=f"quality_blocked: {filter_reason}")
        print("\nDone.")
        return

    # ── Calibration (toggle-gated; default OFF) ────────────────────
    # Runs after the filter settles on a final arke_pct and before the
    # provenance bundle, so the bundle + oracle log + DB store the calibrated
    # value while keeping the raw estimate for provenance. Fails open.
    raw_arke_pct = arke_pct
    if os.getenv("ENABLE_CALIBRATION") == "1":
        from agent.calibration import calibrate
        resolved = db.get_resolved_for_calibration() if DB_AVAILABLE else []
        arke_pct = calibrate(arke_pct, resolved)
        print(f"      Calibration: {raw_arke_pct}% → {arke_pct}%")
        # Recompute edge/position in case calibration shifted the estimate
        edge = arke_pct - market_pct
        position = "AGREE" if abs(edge) <= 3 else ("BULL" if edge > 0 else "BEAR")
    else:
        raw_arke_pct = None   # don't store if calibration not running

    # ── Provenance bundle (sha256-pinned reasoning trace) ──────────
    # Written in both dry-run and live modes; the DB cid is set only on a live
    # post (when a posted_markets row exists).
    # Merge all citation sources for the provenance bundle
    all_citations = (
        (signal_citations      or []) +
        (forecaster_citations  or []) +
        (grounded_citations    or [])
    )
    reasoning_cid = ""
    try:
        from agent.provenance import assemble_bundle, write_trace
        bundle, _bundle_json, bundle_sha = assemble_bundle(
            condition_id=cid,
            arke_pct=arke_pct,
            market_pct=market_pct,
            question=market.get("question", ""),
            council_signal=signal_report,
            council_forecast=tweet,
            citations=all_citations,
            raw_arke_pct=raw_arke_pct,
            calibrated_arke_pct=(arke_pct if raw_arke_pct is not None else None),
        )
        trace_path = write_trace(bundle, cid)
        reasoning_cid = f"sha256:{bundle_sha}"
        print(f"      Provenance bundle written to {trace_path}")
        print(f"      reasoning_cid: {reasoning_cid}")
    except Exception as e:
        print(f"      Provenance bundle skipped: {e}")

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
                arke_probability_pct=arke_pct,
                news_context=news_context,
            )
            duration_ms = int((time.time() - run_start) * 1000)
            db.record_run(
                "posted",
                market_selected=market.get("question", ""),
                duration_ms=duration_ms,
            )
            print(f"      DB row: {row_id}")
            if reasoning_cid:
                db.set_reasoning_cid(cid, reasoning_cid)

        # ── Onchain oracle log ──────────────────────────────────────
        try:
            from agent.integrations.oracle import log_prediction_onchain
            tx_hash = log_prediction_onchain(
                condition_id=cid,
                question=market.get("question", ""),
                market_pct=market_pct,
                arke_pct=arke_pct,
            )
            if tx_hash:
                print(f"      Oracle: {tx_hash[:20]}...")
                if tx_hash and DB_AVAILABLE:
                    db.record_oracle_log_tx(cid, tx_hash)
            else:
                print(f"      Oracle: skipped (no key or contract)")
        except Exception as e:
            print(f"      Oracle: failed silently ({e})")

        # ── Symbolic stake (commitment device) — OFF unless ENABLE_STAKE=1 ──
        # Never set ENABLE_STAKE=1 on the VPS; only locally for the demo runs.
        if os.getenv("ENABLE_STAKE") == "1" and not dry_run:
            try:
                from agent.integrations.polymarket_stake import place_symbolic_stake
                token_id, side = _resolve_token_and_side(market, arke_pct)
                stx = place_symbolic_stake(
                    cid, token_id, side,
                    float(os.getenv("STAKE_MAX_USDC", "0.5")),
                    os.getenv("POLY_BUILDER_CODE", ""),
                )
                if stx:
                    print(f"      Stake: {stx[:20]}")
                    if DB_AVAILABLE:
                        db.record_stake_tx(cid, stx)
            except Exception as e:
                print(f"      Stake skipped: {e}")

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
    import logging
    # Surface agent.* INFO logs (forecaster/ensemble/base-rate) on the CLI
    # without third-party (httpx/groq) noise. Scoped to __main__ so importing
    # main() from the scheduler leaves the live service's logging untouched.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("agent").setLevel(logging.INFO)
    asyncio.run(main())
