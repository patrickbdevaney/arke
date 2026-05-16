"""
prove_the_loop.py — Arke core proof

Chain:
1. Fetch live Arke feed from Polymarket Gamma API
2. Pick best market (highest volume, genuine uncertainty, non-sports)
3. Call Groq to generate tweet with editorial take
4. Post full tweet with link via OpenTweet API
5. Print result

Run:
  python prove_the_loop.py          # dry run by default — safe, no post
  python prove_the_loop.py --post   # actually posts to @arke_ai, burns a credit
"""

import httpx
import asyncio
import os
import sys
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

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
]

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "arke.markets")


def is_sports(q: str) -> bool:
    return any(kw.lower() in q.lower() for kw in SPORTS_KEYWORDS)


def get_market_url(market: dict) -> str:
    """Build correct Polymarket URL using event slug.
    Format: polymarket.com/event/{event_slug}
    Falls back to market slug if no event slug available.
    """
    events = market.get("events", [])
    if events:
        event_slug = events[0].get("slug", "")
        if event_slug:
            return f"polymarket.com/event/{event_slug}"
    return f"polymarket.com/event/{market.get('slug', '')}"


async def fetch_arke_feed() -> list[dict]:
    """Fetch top non-sports markets with genuine uncertainty."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "active": "true",
                "limit": 100,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
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
    """Pick the single best market to tweet about right now.
    Prefers markets resolving within 30 days — urgency drives engagement.
    Falls back to highest volume if nothing resolves soon.
    """
    import datetime

    today = datetime.date.today()

    for m in feed:
        end_str = m.get("endDateIso", "")
        try:
            end_date = datetime.date.fromisoformat(end_str)
            days_left = (end_date - today).days
            if 0 <= days_left <= 30:
                return m
        except Exception:
            continue

    return feed[0] if feed else None


def generate_tweet(market: dict, groq_api_key: str) -> str:
    """Call Groq to generate an editorial tweet about this market."""
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
- Your reason must be specific — cite a mechanism, a historical pattern, or a named data point. Never say "unchanged strategy" or vague generalities
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
        model="openai/gpt-oss-120b",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()


async def post_to_opentweet(tweet: str) -> dict:
    """Post full tweet including URL directly via OpenTweet API.
    OpenTweet absorbs the X URL cost in their subscription pricing.
    Single tweet, no thread workaround needed.
    """
    api_key = os.getenv("OPENTWEET_API_KEY")
    if not api_key:
        print("      OPENTWEET_API_KEY not set — skipping post")
        print("      Add OPENTWEET_API_KEY to ~/arke/.env")
        return {}

    async with httpx.AsyncClient() as client:
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


async def main():
    print("DEBUG: loading env vars...")
    groq_key = os.getenv("GROQ_API_KEY")
    opentweet_key = os.getenv("OPENTWEET_API_KEY")

    print(f"DEBUG: GROQ_API_KEY      = {groq_key[:10] if groq_key else 'NOT SET'}")
    print(
        f"DEBUG: OPENTWEET_API_KEY = {opentweet_key[:10] if opentweet_key else 'NOT SET'}"
    )
    print(f"DEBUG: DRY_RUN           = {DRY_RUN}")
    print()

    if not groq_key:
        print("ERROR: GROQ_API_KEY not set")
        print("Add GROQ_API_KEY=your_key to ~/arke/.env")
        return

    print("[1/4] Fetching Arke feed...")
    feed = await fetch_arke_feed()
    print(f"      Found {len(feed)} actionable markets")
    for m in feed:
        pct = int(float(m.get("lastTradePrice", 0)) * 100)
        vol = float(m.get("volume24hr", 0))
        print(f"      {pct}% | ${vol:,.0f}/24h | {m['question'][:60]}")

    print("\n[2/4] Picking best market...")
    market = pick_best_market(feed)
    if not market:
        print("      No suitable market found")
        return
    pct = int(float(market.get("lastTradePrice", 0)) * 100)
    vol = float(market.get("volume24hr", 0))
    market_url = get_market_url(market)
    print(f"      Selected: {market['question']}")
    print(f"      {pct}% YES | ${vol:,.0f}/24h | ends {market.get('endDateIso')}")
    print(f"      URL: {market_url}")

    print("\n[3/4] Generating tweet...")
    tweet = generate_tweet(market, groq_key)

    print(f"\n{'='*60}")
    print("TWEET:")
    print(tweet)
    print(f"{'='*60}")
    print(f"Length: {len(tweet)} chars")

    print("\n[4/4] Posting to OpenTweet...")
    if DRY_RUN:
        print("      DRY RUN — no post sent")
        print(f"      Verify the URL resolves before posting:")
        print(f"      https://{market_url}")
        print(f"\n      Run with --post flag to post for real:")
        print(f"      python prove_the_loop.py --post")
    else:
        if not opentweet_key:
            print("      ERROR: OPENTWEET_API_KEY not set")
            print("      Add OPENTWEET_API_KEY to ~/arke/.env")
            return
        result = await post_to_opentweet(tweet)
        if result:
            post_id = result.get("posts", [{}])[0].get("id", "unknown")
            print(f"      Success: post id {post_id}")
            print(f"      Check @arke_ai on X")
        else:
            print(f"      Failed — check HTTP status and response above")

    print(f"\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
