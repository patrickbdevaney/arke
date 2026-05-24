"""
agent/agents/resolver.py — Market resolution checker

Runs daily. Finds all markets past their end_date that aren't marked resolved.
Checks Gamma API for resolution status. Updates db with outcome and accuracy.

Provides:
  check_resolutions() -> dict   — counts of markets checked and resolved
"""

import json
import logging
import os
import re

import httpx

from agent.db import ArkeDB

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
ARCSCAN = "https://testnet.arcscan.app"


def _per_call_skill_bps(arke_pct: int, outcome_yes: bool) -> int:
    """Per-call Murphy (1973) skill score vs a flat-50% reference, in bps.

    skill = 1 - Brier/Brier_ref, where Brier_ref for a single call is the
    (0.5 - outcome)^2 = 0.25 of an always-50% forecast. Positive = better than
    a coin flip on this call. Mirrors db.get_dual_scores() for the aggregate.
    """
    p = max(0.01, min(0.99, arke_pct / 100.0))
    y = 1.0 if outcome_yes else 0.0
    brier = (p - y) ** 2
    ref = (0.5 - y) ** 2  # = 0.25
    skill = (1.0 - brier / ref) if ref > 0 else 0.0
    return round(skill * 10000)


def _tweet_id_from_url(url: str | None) -> str | None:
    """Extract the numeric status id from an x.com/.../status/<id> URL."""
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else None


def compose_resolution_post(
    question: str | None,
    arke_pct: int | None,
    market_pct: int | None,
    outcome: str,
    was_correct: bool,
    resolve_tx: str = "",
) -> str:
    """Compose the RESOLUTION tweet body.

    RESOLVED: <question ≤80 chars>
    Arke: X% · Market: Y% · Outcome: YES/NO
    Directional: ✓ correct / ✗ wrong  |  Skill: ±N bps
    ⛓ <oracle link>
    """
    q = (question or "")[:80]
    arke_s = f"{arke_pct}%" if arke_pct is not None else "—"
    mkt_s = f"{market_pct}%" if market_pct is not None else "—"
    dir_s = "✓ correct" if was_correct else "✗ wrong"
    skill_s = ""
    if arke_pct is not None:
        skill_s = f"  |  Skill: {_per_call_skill_bps(arke_pct, outcome == 'YES'):+d} bps"

    if resolve_tx:
        link = f"{ARCSCAN}/tx/{resolve_tx}"
    elif os.getenv("ORACLE_CONTRACT_ADDRESS"):
        link = f"{ARCSCAN}/address/{os.getenv('ORACLE_CONTRACT_ADDRESS')}"
    else:
        link = "https://arke.live/oracle"

    return "\n".join([
        f"RESOLVED: {q}",
        f"Arke: {arke_s} · Market: {mkt_s} · Outcome: {outcome}",
        f"Directional: {dir_s}{skill_s}",
        f"⛓ {link}",
    ])


async def _post_resolution(
    db: ArkeDB,
    cid: str,
    question: str | None,
    arke_pct: int | None,
    market_pct: int | None,
    outcome: str,
    was_correct: bool,
    resolve_tx: str,
) -> None:
    """Compose + post the RESOLUTION tweet, quote-tweeting the original call
    when its x_post_url is known. Fails open — never raises into the loop."""
    text = compose_resolution_post(
        question, arke_pct, market_pct, outcome, was_correct, resolve_tx)

    x_url = None
    try:
        with db._conn() as conn:
            r = conn.execute(
                "SELECT x_post_url FROM posted_markets "
                "WHERE condition_id = ? AND x_post_url IS NOT NULL "
                "AND x_post_url != '' ORDER BY posted_at_ts DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if r:
                x_url = r["x_post_url"]
    except Exception:
        pass

    quote_id = _tweet_id_from_url(x_url)
    try:
        from agent.integrations.opentweet import post_tweet
        result = await post_tweet(text, quote_tweet_id=quote_id)
        if result:
            logger.info(f"[Resolver] RESOLUTION posted for {cid[:12]}"
                        f"{' (quote)' if quote_id else ''}")
        else:
            logger.warning(f"[Resolver] RESOLUTION post empty for {cid[:12]}")
    except Exception as e:
        logger.warning(f"[Resolver] RESOLUTION post failed (continuing): {e}")


def _parse_outcome(market_data: dict) -> str | None:
    """Return 'YES', 'NO', or None given a Gamma market response."""
    if not market_data.get("closed"):
        return None

    prices = market_data.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            prices = None
    if not prices or len(prices) < 2:
        return None

    try:
        yes = float(prices[0])
        no = float(prices[1])
    except (TypeError, ValueError):
        return None

    if yes >= 0.99 and no <= 0.01:
        return "YES"
    if no >= 0.99 and yes <= 0.01:
        return "NO"
    return None


def _arke_call(post: dict) -> str | None:
    """Reduce a stored post to Arke's directional call: 'YES', 'NO', or None.

    Council-era rows carry arke_probability_pct (Arke's own estimate), which is
    the most direct signal: >50 means Arke leaned YES. Position labels
    (AGREE/BULL/BEAR) are relative to the market, so they can't be scored
    directly — e.g. BULL on a 20%->35% market is still a NO call. We use them
    only as a fallback for legacy rows that predate arke_probability_pct.
    """
    arke_pct = post.get("arke_probability_pct")
    if arke_pct is not None:
        try:
            return "YES" if int(arke_pct) > 50 else "NO"
        except (TypeError, ValueError):
            pass

    # Legacy fallback: derive direction from the position label vs the market.
    pos = (post.get("arke_position") or "NEUTRAL").upper()
    market_pct = int(post.get("probability_pct") or 0)
    if pos in ("AGREE", "NEUTRAL"):
        return "YES" if market_pct > 50 else "NO"
    if pos == "DISAGREE":
        return "NO" if market_pct > 50 else "YES"
    if pos == "BULL":
        return "YES"
    if pos == "BEAR":
        return "NO"
    return None


async def _fetch_market(client: httpx.AsyncClient, condition_id: str) -> dict | None:
    try:
        # Gamma excludes closed/resolved markets from /markets by default, so a
        # bare condition_ids query returns [] for every settled market — which is
        # exactly the set the resolver needs. closed=true includes them. (The
        # param is condition_ids, plural; condition_id singular is ignored and
        # returns an unfiltered list of arbitrary markets.)
        r = await client.get(
            GAMMA_URL, params={"condition_ids": condition_id, "closed": "true"}
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(f"[Resolver] fetch {condition_id[:12]} failed: {e}")
    return None


async def check_resolutions(post: bool = False) -> dict:
    """Find unresolved past-end-date markets, check Gamma, mark resolutions.

    When post=True, each newly resolved call also fires a RESOLUTION tweet
    (quote-tweeting the original when known). Gated so dry runs never post.
    """
    db = ArkeDB()
    unresolved = db.get_unresolved_past_enddate()
    logger.info(f"[Resolver] {len(unresolved)} unresolved markets past end_date")

    resolved_count = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        for row in unresolved:
            cid = row.get("condition_id", "")
            if not cid:
                continue

            market = await _fetch_market(client, cid)
            if not market:
                continue

            outcome = _parse_outcome(market)
            if outcome is None:
                continue

            # Determine was_correct based on Arke's position from db
            posts = []
            try:
                with db._conn() as conn:
                    posts = [
                        dict(r)
                        for r in conn.execute(
                            """
                            SELECT arke_position, probability_pct, arke_probability_pct
                            FROM posted_markets
                            WHERE condition_id = ? AND resolved = 0
                            """,
                            (cid,),
                        ).fetchall()
                    ]
            except Exception as e:
                logger.warning(f"[Resolver] db read failed for {cid[:12]}: {e}")
                continue

            was_correct = False
            for p in posts:
                predicted = _arke_call(p)
                if predicted is not None and predicted == outcome:
                    was_correct = True
                    break

            db.mark_resolved(cid, outcome, was_correct)
            resolved_count += 1
            logger.info(
                f"[Resolver] {cid[:12]} resolved {outcome} | correct={was_correct} "
                f"| {row.get('question', '')[:60]}"
            )

            # Arke's own estimate + the market consensus at post time, for the
            # RESOLUTION tweet. First post with a stored estimate wins.
            arke_pct = market_pct = None
            for p in posts:
                if arke_pct is None and p.get("arke_probability_pct") is not None:
                    arke_pct = int(p["arke_probability_pct"])
                if market_pct is None and p.get("probability_pct") is not None:
                    market_pct = int(p["probability_pct"])

            # Write the resolution onchain so the Brier ledger updates. Fails
            # silently — a chain error must never abort the resolver loop.
            resolve_tx = ""
            try:
                from agent.integrations.oracle import resolve_prediction_onchain
                resolve_tx = resolve_prediction_onchain(cid, outcome == "YES") or ""
                if resolve_tx:
                    logger.info(f"[Resolver] onchain resolution {cid[:12]} -> {resolve_tx[:20]}")
                    db.record_oracle_resolution_tx(cid, resolve_tx)
            except Exception as e:
                logger.warning(f"[Resolver] onchain resolve failed (continuing): {e}")

            # RESOLUTION quote-tweet (post=True only). Fails open.
            if post:
                await _post_resolution(
                    db, cid, row.get("question"), arke_pct, market_pct,
                    outcome, was_correct, resolve_tx,
                )

    # After all resolutions settle, push Arke's current skill score to the
    # ERC-8004 Reputation Registry (Phase 5). Fails open — never blocks.
    if resolved_count > 0:
        try:
            from agent.integrations.erc8004_reputation import write_reputation
            scores = db.get_dual_scores()
            if scores.get("n_resolved", 0) > 0:
                write_reputation(scores["skill_bps"], scores["directional_pct"])
        except Exception as e:
            logger.debug(f"[Resolver] reputation write skipped: {e}")

    return {
        "markets_checked": len(unresolved),
        "markets_resolved": resolved_count,
    }
