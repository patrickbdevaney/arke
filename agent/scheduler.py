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


def run_loop():
    """Wraps asyncio.run(loop_main(post=True)) in try/except. Logs duration."""
    start = time.time()
    logger.info("=== Arke Agent Starting ===")
    _log_db_stats()
    try:
        asyncio.run(loop_main(post=True))
        duration = time.time() - start
        logger.info("=== Run complete in %.1fs — POSTED ===", duration)
    except Exception as e:
        duration = time.time() - start
        logger.exception("Run failed after %.1fs: %s", duration, e)


def run_resolver():
    """Wraps asyncio.run(check_resolutions()) in try/except."""
    start = time.time()
    logger.info("=== Resolver Starting ===")
    try:
        result = asyncio.run(check_resolutions())
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
