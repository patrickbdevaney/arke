"""
agent/scheduler.py — Arke autonomous scheduler

Runs the full pipeline every 6 hours.
Runs the resolution checker every 24 hours.
Survives all exceptions — logs and continues.

Usage:
  python agent/scheduler.py         # start autonomous agent
  python agent/scheduler.py --once  # run once and exit (for testing)
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Keep stdout (prints from prove_the_loop) line-buffered so it interleaves
# with logger output in the right order when both are piped.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# Make prove_the_loop importable from the project root regardless of how we're invoked.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("arke.scheduler")

# Quiet down noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import schedule  # noqa: E402

from prove_the_loop import main as loop_main  # noqa: E402
from agent.agents.resolver import check_resolutions  # noqa: E402
from agent.db import ArkeDB  # noqa: E402


def _log_db_stats():
    try:
        db = ArkeDB()
        s = db.stats()
        last_q = (s.get("last_post_question") or "")[:50]
        logger.info(
            "DB: %d posts, %d resolved, last: %s",
            s.get("total_posted", 0),
            s.get("total_resolved", 0) or 0,
            last_q or "(none)",
        )
    except Exception as e:
        logger.warning("DB stats unavailable: %s", e)


async def post_market_watch(db, post: bool = False):
    """Post a structured 'watching' summary instead of a stale re-post.

    Fires from run_loop() when every actionable market is within its
    per-category cooldown (loop_main returns "all_cooldown"). Picks the top 3
    markets not posted in the last 6h and tweets that Arke is monitoring rather
    than re-running the council on a stale market. Gated on post=True so dry
    runs never tweet. Fails open — any error is logged and ignored.
    """
    try:
        from prove_the_loop import fetch_arke_feed
        feed = await fetch_arke_feed()
    except Exception as e:
        logger.warning("[MarketWatch] feed fetch failed (skipping): %s", e)
        return None

    top3 = []
    for m in feed[:20]:
        try:
            fresh = not db.already_posted(m.get("conditionId", ""), cooldown_hours=6)
        except Exception:
            fresh = True
        if fresh:
            top3.append(m)
        if len(top3) >= 3:
            break

    if not top3:
        logger.info("[MarketWatch] nothing fresh to watch — skipping")
        return None

    lines = ["Arke is monitoring markets. No new high-edge call this cycle."]
    for m in top3:
        q = (m.get("question", "") or "")[:60]
        try:
            pct = int(float(m.get("lastTradePrice", 0) or 0) * 100)
            lines.append(f"Watching: {q} ({pct}%)")
        except Exception:
            lines.append(f"Watching: {q}")
    text = "\n".join(lines)
    if len(text) > 280:  # X hard limit
        text = text[:277] + "..."

    if not post:
        logger.info("[MarketWatch] DRY RUN — would post:\n%s", text)
        return text

    try:
        from agent.integrations.opentweet import post_tweet
        result = await post_tweet(text)
        if result:
            logger.info("[MarketWatch] posted watch summary")
        else:
            logger.warning("[MarketWatch] post returned empty — see [X] logs")
        return result
    except Exception as e:
        logger.warning("[MarketWatch] post failed (continuing): %s", e)
        return None


def run_loop():
    """Wraps asyncio.run(loop_main(post=True)) in try/except. Logs duration.

    If the loop reports every market is in cooldown ("all_cooldown"), posts a
    MARKET WATCH summary instead of letting the loop re-post a stale market.
    """
    start = time.time()
    logger.info("=== Arke Agent Starting ===")
    _log_db_stats()
    try:
        status = asyncio.run(loop_main(post=True))
        if status == "all_cooldown":
            logger.info("=== All markets in cooldown — posting MARKET WATCH ===")
            try:
                asyncio.run(post_market_watch(ArkeDB(), post=True))
            except Exception as e:
                logger.warning("MARKET WATCH post failed (continuing): %s", e)
        duration = time.time() - start
        logger.info("=== Run complete in %.1fs ===", duration)
    except Exception as e:
        duration = time.time() - start
        logger.exception("Run failed after %.1fs: %s", duration, e)


def run_resolver():
    """Wraps asyncio.run(check_resolutions()) in try/except."""
    start = time.time()
    logger.info("=== Resolver Starting ===")
    try:
        result = asyncio.run(check_resolutions(post=True))
        duration = time.time() - start
        logger.info(
            "=== Resolver complete in %.1fs: checked=%s resolved=%s ===",
            duration,
            result.get("markets_checked", 0),
            result.get("markets_resolved", 0),
        )
    except Exception as e:
        duration = time.time() - start
        logger.exception("Resolver failed after %.1fs: %s", duration, e)


def main():
    schedule.every(6).hours.do(run_loop)
    schedule.every(24).hours.do(run_resolver)

    if "--once" in sys.argv:
        logger.info("Running once and exiting (--once flag)")
        run_loop()
        return

    next_run = schedule.next_run()
    banner = (
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║   ARKE — Autonomous Prediction Market Intelligence Agent     ║\n"
        "║   Loop:     every 6 hours                                    ║\n"
        "║   Resolver: every 24 hours                                   ║\n"
        f"║   Next run: {str(next_run)[:50]:<50}║\n"
        "╚══════════════════════════════════════════════════════════════╝"
    )
    print(banner, flush=True)
    logger.info("Scheduler started — next run at %s", next_run)

    # Run once immediately on startup. Also run the resolver on startup: the
    # `schedule` library is in-memory, so every restart (deploy, reboot, crash)
    # resets the 24h resolver timer. Without a startup run, frequent restarts
    # would starve resolutions and the Brier ledger would never update. The
    # resolver is idempotent — it only touches unresolved, past-end-date rows.
    run_loop()
    run_resolver()

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.exception("schedule.run_pending failed: %s", e)
        time.sleep(60)


if __name__ == "__main__":
    main()
