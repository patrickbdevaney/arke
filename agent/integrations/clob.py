"""
agent/integrations/clob.py — Polymarket CLOB microstructure reader.
Read-only public endpoints, no auth required. Fails open (all-None on error).
"""
import json as _json
import logging
import httpx

log = logging.getLogger(__name__)
CLOB_BASE = "https://clob.polymarket.com"


def get_microstructure(token_id: str) -> dict:
    """Return {midpoint, spread, best_bid, best_ask, book_hash} for a YES token.
    All values may be None on any failure."""
    out = {"midpoint": None, "spread": None, "best_bid": None,
           "best_ask": None, "book_hash": None}
    if not token_id:
        return out
    try:
        with httpx.Client(timeout=8.0) as c:
            mr = c.get(f"{CLOB_BASE}/midpoint", params={"token_id": token_id})
            if mr.status_code == 200:
                out["midpoint"] = float(mr.json().get("mid", 0)) or None
            sr = c.get(f"{CLOB_BASE}/spread", params={"token_id": token_id})
            if sr.status_code == 200:
                out["spread"] = float(sr.json().get("spread", 0))
            br = c.get(f"{CLOB_BASE}/book", params={"token_id": token_id})
            if br.status_code == 200:
                book = br.json()
                out["book_hash"] = book.get("hash")
                bids = book.get("bids") or []
                asks = book.get("asks") or []
                if bids:
                    out["best_bid"] = float(bids[-1].get("price", 0)) or None
                if asks:
                    out["best_ask"] = float(asks[-1].get("price", 0)) or None
    except Exception as e:
        log.debug(f"[CLOB] fetch failed: {e}")
    return out


def extract_yes_token_id(market: dict) -> str:
    """Parse clobTokenIds (JSON-string or list) → YES token id string, or ''."""
    try:
        ids = market.get("clobTokenIds")
        if not ids:
            return ""
        arr = _json.loads(ids) if isinstance(ids, str) else ids
        return arr[0] if arr else ""
    except Exception:
        return ""
