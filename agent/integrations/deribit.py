"""
agent/integrations/deribit.py — crypto option-implied probabilities.
Public Deribit API, no auth. For 'BTC/ETH above $X by date' markets,
approximates Pr(ITM) ≈ |call delta| (risk-neutral proxy). Fails open.
"""
import re
import logging
import httpx

log = logging.getLogger(__name__)
DERIBIT_BASE = "https://www.deribit.com/api/v2"


def _detect_crypto_threshold(question: str):
    """Return (currency, strike_int) or (None, None) if not a price-threshold market."""
    q = (question or "").lower()
    if "bitcoin" in q or "btc" in q:
        cur = "BTC"
    elif "ethereum" in q or "eth" in q:
        cur = "ETH"
    else:
        return None, None
    m = re.search(r"\$?\s?(\d[\d,]{2,})", question or "")
    if not m:
        return None, None
    strike = int(m.group(1).replace(",", ""))
    return cur, strike


def crypto_context(question: str) -> tuple[str, list]:
    """Option-implied Pr for crypto price-threshold markets. Fails open."""
    cur, strike = _detect_crypto_threshold(question)
    if not cur or not strike:
        return "", []
    try:
        with httpx.Client(timeout=8.0) as c:
            # Spot price
            idx = c.get(f"{DERIBIT_BASE}/public/get_index_price",
                        params={"index_name": f"{cur.lower()}_usd"})
            spot = None
            if idx.status_code == 200:
                spot = idx.json().get("result", {}).get("index_price")

            # Option chain — find nearest call strike
            inst = c.get(f"{DERIBIT_BASE}/public/get_instruments",
                         params={"currency": cur, "kind": "option",
                                 "expired": "false"})
            if inst.status_code != 200:
                return "", []
            calls = [i for i in inst.json().get("result", [])
                     if i.get("option_type") == "call"]
            if not calls:
                return "", []
            best = min(calls,
                       key=lambda i: abs((i.get("strike") or 0) - strike))

            # Delta from orderbook greeks
            ob = c.get(f"{DERIBIT_BASE}/public/get_order_book",
                       params={"instrument_name": best["instrument_name"]})
            if ob.status_code != 200:
                return "", []
            delta = (ob.json().get("result", {})
                     .get("greeks", {}).get("delta"))
            if delta is None:
                return "", []

            pr = int(round(abs(delta) * 100))
            ctx = (
                f"DERIBIT: {cur} spot ≈ {spot}; nearest call "
                f"(strike {best.get('strike')}) delta {delta:.2f} "
                f"⇒ option-implied Pr(above) ≈ {pr}%. "
                f"Anchor your estimate on this risk-neutral probability."
            )
            cite = [{
                "claim": (f"Deribit {best['instrument_name']} "
                          f"delta {delta:.2f}"),
                "source_url": f"https://www.deribit.com/options/{cur}",
                "retrieved_at": "",
                "content_sha256": "",
            }]
            return ctx, cite
    except Exception as e:
        log.debug(f"[Deribit] failed: {e}")
    return "", []
