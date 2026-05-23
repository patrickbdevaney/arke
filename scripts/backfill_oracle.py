#!/usr/bin/env python3
"""
scripts/backfill_oracle.py — replay historical SQLite rows to the oracle contract.

Turns the existing posting history into onchain artifacts: one logPrediction per
posted market, one resolvePrediction per resolved market.

Idempotent — safe to re-run. Only rows whose oracle_log_tx / oracle_resolve_tx
are still NULL get written, so re-running never double-logs.

Reads the LOCAL repo-root arke.db (the dev copy). Do NOT point this at the
production VPS arke.db — the operator runs that separately after syncing.

Usage:
    python scripts/backfill_oracle.py [--dry-run]
"""

import os
import sys
import time

# Make the repo root importable when invoked as `python scripts/backfill_oracle.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from agent.db import ArkeDB  # noqa: E402
from agent.integrations.oracle import (  # noqa: E402
    log_prediction_onchain,
    resolve_prediction_onchain,
)


def _arke_pct(row: dict) -> int:
    """Arke's estimate, falling back to the market consensus for legacy rows."""
    arke = row.get("arke_probability_pct")
    if arke is None:
        arke = row.get("probability_pct")
    return int(arke or 0)


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db = ArkeDB()

    with db._conn() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT condition_id, question, probability_pct,
                       arke_probability_pct, resolved, resolution,
                       oracle_log_tx, oracle_resolve_tx
                FROM posted_markets
                ORDER BY posted_at_ts ASC
                """
            ).fetchall()
        ]

    to_log = [r for r in rows if r.get("condition_id") and not r.get("oracle_log_tx")]
    to_resolve = [
        r
        for r in rows
        if r.get("condition_id")
        and r.get("resolved") == 1
        and r.get("resolution") in ("YES", "NO")
        and not r.get("oracle_resolve_tx")
    ]
    already_logged = sum(1 for r in rows if r.get("oracle_log_tx"))

    print(
        f"[backfill] {len(rows)} rows in arke.db | "
        f"{len(to_log)} need logging | {len(to_resolve)} need resolution | "
        f"{already_logged} already logged"
    )

    if dry_run:
        print("[backfill] DRY RUN — no transactions will be sent")
        for r in to_log:
            print(
                f"  would log     {r['condition_id'][:14]}  "
                f"market={r.get('probability_pct')}%  arke={_arke_pct(r)}%  "
                f"| {(r.get('question') or '')[:50]}"
            )
        for r in to_resolve:
            print(f"  would resolve {r['condition_id'][:14]} -> {r.get('resolution')}")
        print(
            f"[backfill] would write {len(to_log)} predictions, "
            f"{len(to_resolve)} resolutions"
        )
        return

    logged = 0
    for r in to_log:
        cid = r["condition_id"]
        tx = log_prediction_onchain(
            condition_id=cid,
            question=r.get("question", ""),
            market_pct=int(r.get("probability_pct") or 0),
            arke_pct=_arke_pct(r),
        )
        if tx:
            db.record_oracle_log_tx(cid, tx)
            logged += 1
            print(f"  logged {logged}/{len(to_log)}  {cid[:14]} -> {tx[:20]}")
        else:
            print(
                f"  skip   {cid[:14]} (no tx — check ARC_PRIVATE_KEY / "
                f"ORACLE_CONTRACT_ADDRESS / RPC)"
            )
        time.sleep(2)  # nonce fetched fresh per tx; give Arc room between sends

    resolved = 0
    for r in to_resolve:
        cid = r["condition_id"]
        tx = resolve_prediction_onchain(cid, r.get("resolution") == "YES")
        if tx:
            db.record_oracle_resolution_tx(cid, tx)
            resolved += 1
            print(f"  resolved {resolved}/{len(to_resolve)}  {cid[:14]} -> {tx[:20]}")
        else:
            print(f"  skip   {cid[:14]} (resolve returned no tx)")
        time.sleep(2)

    print(
        f"[backfill] {logged} predictions logged, {resolved} resolutions written, "
        f"{already_logged} skipped (already logged)."
    )


if __name__ == "__main__":
    main()
