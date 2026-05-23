"""
agent/integrations/polymarket_stake.py — symbolic stake (commitment device).

Places a small REAL Polymarket position behind a call so each forecast carries
a cryptographic commitment, not just words. This is a commitment device, not a
trading strategy — sizes are tiny and hard-capped.

Safety model (mirrors the oracle's deploy-safe pattern):
  * No STAKE_WALLET_PRIVATE_KEY  → silent no-op (returns "").
  * size_usdc over the per-stake cap, or lifetime cap exceeded → raise
    StakeCapExceeded LOUDLY (never a silent overspend).
  * Any signing/network error → returns "" (never blocks the posting loop).

The staking wallet key is SEPARATE from ARC_PRIVATE_KEY (different chain,
different key) and is read only from STAKE_WALLET_PRIVATE_KEY.
"""

import os
import time
import logging

import httpx

from agent.db import ArkeDB

log = logging.getLogger(__name__)

CLOB_V2_ORDER_URL = "https://clob.polymarket.com/order"
POLYGON_CHAIN_ID = 137


class StakeCapExceeded(Exception):
    """Raised (loudly) when a stake would breach the per-stake or lifetime cap."""


def _db() -> ArkeDB:
    return ArkeDB(os.getenv("ARKE_DB_PATH") or None)


def _builder_bytes32(builder_code: str) -> bytes:
    """Encode the builder code as the 32-byte `builder` order field."""
    return bytes.fromhex(builder_code.lstrip("0x").ljust(64, "0")[:64])


def place_symbolic_stake(
    condition_id: str,
    token_id: str,
    side: str,          # "YES" or "NO"
    size_usdc: float,
    builder_code: str,
) -> str:
    """Place a small real Polymarket V2 position as a cryptographic commitment.
    Returns order hash or ''. Fails silently — never blocks the posting loop.
    This is a commitment device, not a trading strategy."""
    per_stake_cap = float(os.getenv("STAKE_MAX_USDC", "0.60"))
    lifetime_cap = float(os.getenv("STAKE_LIFETIME_CAP_USDC", "9.0"))

    # 1. Per-stake cap — a misconfigured oversize must always be loud.
    if size_usdc > per_stake_cap:
        raise StakeCapExceeded(
            f"stake {size_usdc} USDC exceeds STAKE_MAX_USDC {per_stake_cap}"
        )

    # 2. Deploy safety: no key → silent no-op (same as oracle).
    private_key = os.getenv("STAKE_WALLET_PRIVATE_KEY", "")
    if not private_key:
        log.debug("[Stake] STAKE_WALLET_PRIVATE_KEY not set — skipping stake")
        return ""

    # 3. Lifetime cap — loud refusal before any tx.
    db = _db()
    already = db.get_total_staked_usdc()
    if already + size_usdc > lifetime_cap:
        raise StakeCapExceeded(
            f"lifetime stake {already + size_usdc:.2f} USDC would exceed "
            f"STAKE_LIFETIME_CAP_USDC {lifetime_cap} (already {already:.2f})"
        )

    if not token_id:
        log.warning("[Stake] no token_id resolved for %s — skipping", condition_id[:12])
        return ""

    # 4. Build, sign and post the order. Any failure here is non-fatal.
    try:
        from eth_account import Account
        from eth_account.messages import encode_typed_data

        account = Account.from_key(private_key)

        # Polymarket CLOB V2 limit-order struct. Amounts are integer USDC base
        # units (6 decimals). A symbolic stake buys `size_usdc` of the chosen
        # outcome at up to 0.99 so it fills.
        maker_amount = int(round(size_usdc * 1_000_000))
        taker_amount = int(round(size_usdc / 0.99 * 1_000_000))
        order = {
            "salt": int(time.time() * 1000),
            "maker": account.address,
            "signer": account.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(token_id),
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": "0",
            "side": 0 if side == "YES" else 1,   # 0 = BUY YES, 1 = BUY NO
            "signatureType": 0,
            # builder attribution — 32-byte field per the V2 builder extension.
            "builder": "0x" + _builder_bytes32(builder_code).hex(),
        }

        typed = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Order": [
                    {"name": "salt", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "signer", "type": "address"},
                    {"name": "taker", "type": "address"},
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "feeRateBps", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "signatureType", "type": "uint8"},
                    {"name": "builder", "type": "bytes32"},
                ],
            },
            "domain": {
                "name": "Polymarket CTF Exchange",
                "version": "1",
                "chainId": POLYGON_CHAIN_ID,
                "verifyingContract": os.getenv(
                    "POLY_EXCHANGE_ADDRESS",
                    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
                ),
            },
            "primaryType": "Order",
            "message": {
                **order,
                "tokenId": int(order["tokenId"]),
                "makerAmount": int(order["makerAmount"]),
                "takerAmount": int(order["takerAmount"]),
                "expiration": 0,
                "nonce": 0,
                "feeRateBps": 0,
                "builder": _builder_bytes32(builder_code),
            },
        }

        signed = Account.sign_message(encode_typed_data(full_message=typed), private_key)
        signature = signed.signature.hex()

        resp = httpx.post(
            CLOB_V2_ORDER_URL,
            json={"order": order, "signature": signature, "owner": account.address},
            timeout=20.0,
        )
        if resp.status_code not in (200, 201):
            log.warning("[Stake] order rejected %s: %s", resp.status_code, resp.text[:200])
            return ""

        data = resp.json()
        order_hash = data.get("orderHash") or data.get("orderID") or data.get("id") or ""
        if order_hash:
            db.record_stake(condition_id, side, size_usdc, order_hash, order_hash)
            log.info("[Stake] placed %s %.2f USDC on %s -> %s",
                     side, size_usdc, condition_id[:12], order_hash[:20])
        return order_hash

    except StakeCapExceeded:
        raise
    except Exception as e:
        log.warning("[Stake] failed (continuing): %s", e)
        return ""
