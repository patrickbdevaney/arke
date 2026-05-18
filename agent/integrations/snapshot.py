"""
agent/integrations/snapshot.py — Snapshot DAO governance signal source

GraphQL endpoint: https://hub.snapshot.org/graphql
No authentication required.

Provides:
  fetch_active_proposals(limit=10) -> list[dict]   — live governance votes
  proposal_to_signal(proposal) -> str              — human-readable signal string
"""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://hub.snapshot.org/graphql"

QUERY = """
{
  proposals(first: %d, where: {state: "active"}, orderBy: "created", orderDirection: desc) {
    id title body state start end scores_total votes space { id name }
  }
}
"""


async def fetch_active_proposals(limit: int = 10) -> list[dict]:
    """Active Snapshot governance proposals. Empty list on failure."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                GRAPHQL_URL,
                json={"query": QUERY % limit},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code != 200:
                logger.warning(f"[Snapshot] HTTP {r.status_code}")
                return []
            data = r.json()
            proposals = (data.get("data") or {}).get("proposals", []) or []
            logger.info(f"[Snapshot] {len(proposals)} active proposals")
            return proposals
    except Exception as e:
        logger.warning(f"[Snapshot] fetch_active_proposals failed: {e}")
        return []


def proposal_to_signal(proposal: dict) -> str:
    """Format proposal as a one-line LLM context signal."""
    space = (proposal.get("space") or {}).get("name", "?")
    title = proposal.get("title", "(untitled)")
    votes = proposal.get("votes", 0)
    end_ts = proposal.get("end", 0)
    try:
        end_str = datetime.fromtimestamp(int(end_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        end_str = "?"
    return f"{space}: {title} — {votes} votes, ends {end_str}"
