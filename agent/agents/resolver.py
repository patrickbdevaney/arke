"""
agent/agents/resolver.py — Market resolution checker

Runs daily. Finds all markets past their end_date that aren't marked resolved.
Checks Gamma API for resolution status. Updates db with outcome and accuracy.

Provides:
  check_resolutions() -> dict   — counts of markets checked and resolved
"""

import json
import logging

import httpx

from agent.db import ArkeDB

logger = logging.getLogger(__name__)

GAMMA_URL = "https://gamma-api.polymarket.com/markets"


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


async def check_resolutions() -> dict:
    """Find unresolved past-end-date markets, check Gamma, mark resolutions."""
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

            # Write the resolution onchain so the Brier ledger updates. Fails
            # silently — a chain error must never abort the resolver loop.
            try:
                from agent.integrations.oracle import resolve_prediction_onchain
                tx = resolve_prediction_onchain(cid, outcome == "YES")
                if tx:
                    logger.info(f"[Resolver] onchain resolution {cid[:12]} -> {tx[:20]}")
                    db.record_oracle_resolution_tx(cid, tx)
            except Exception as e:
                logger.warning(f"[Resolver] onchain resolve failed (continuing): {e}")

    return {
        "markets_checked": len(unresolved),
        "markets_resolved": resolved_count,
    }
