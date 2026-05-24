"""
agent/integrations/erc8004_reputation.py — ERC-8004 Reputation Registry writer.

Writes Arke's current Brier skill score to the ERC-8004 Reputation Registry
on Arc testnet as a self-attestation. Called daily after the resolver runs.

The Reputation Registry's giveFeedback(agentId, value, decimals, tag1, tag2)
function writes a signed int128 score. We write:
  agentId  = 20360
  value    = skill_bps (e.g. 5100 for +51% skill)
  decimals = 0
  tag1     = keccak256("brier_skill")
  tag2     = keccak256("directional")
as a self-attestation. The standard envisions client-written feedback; this
is self-reported and clearly labelled as such (on the dashboard + in the README).

Deployment was verified live on Arc testnet (chainId 5042002) before this module
was wired in: the Reputation Registry at the address below is a deployed
EIP-1967 proxy.

Fails open — any error (no key, RPC down, ABI mismatch, revert) is logged and
ignored. Never blocks the resolver or the posting loop.
"""
import os
import logging

log = logging.getLogger(__name__)

REP_REGISTRY = "0x8004B663056A597Dffe9eCcC1965A193B7388713"
AGENT_ID = 20360

# Minimal ABI for giveFeedback only.
REP_ABI = [{"inputs": [
    {"name": "agentId",  "type": "uint256"},
    {"name": "value",    "type": "int128"},
    {"name": "decimals", "type": "uint8"},
    {"name": "tag1",     "type": "bytes32"},
    {"name": "tag2",     "type": "bytes32"},
], "name": "giveFeedback", "outputs": [], "stateMutability": "nonpayable",
   "type": "function"}]


def _inject_poa_middleware(w3) -> None:
    """Inject the POA extra-data middleware, tolerant of web3 6.x vs 7.x.

    web3 7.x exposes ExtraDataToPOAMiddleware; web3 6.x exposes
    geth_poa_middleware. We try both and silently no-op if neither is present —
    the write still works on chains that don't need the shim.
    """
    try:
        from web3.middleware import ExtraDataToPOAMiddleware  # web3 7.x
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return
    except Exception:
        pass
    try:
        from web3.middleware import geth_poa_middleware  # web3 6.x
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        log.debug("[ERC8004Rep] no POA middleware available — continuing")


def write_reputation(skill_bps: int, directional_pct: int) -> str | None:
    """Write Arke's current Brier skill score to the Reputation Registry.
    Returns the tx hash or None on failure. Fails open."""
    key = os.getenv("ARC_PRIVATE_KEY")
    rpc = (os.getenv("ARC_RPC_PRIMARY")
           or os.getenv("ARC_RPC_FALLBACK")
           or os.getenv("ARC_RPC_URL")
           or "https://rpc.testnet.arc.network")
    if not key:
        log.debug("[ERC8004Rep] ARC_PRIVATE_KEY not set — skipping")
        return None
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc))
        _inject_poa_middleware(w3)
        acct = w3.eth.account.from_key(key)
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(REP_REGISTRY), abi=REP_ABI)

        tag_brier_skill = Web3.keccak(text="brier_skill")
        tag_directional = Web3.keccak(text="directional")

        tx = contract.functions.giveFeedback(
            AGENT_ID, int(skill_bps), 0, tag_brier_skill, tag_directional
        ).build_transaction({
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "gas": 150_000,
            "gasPrice": w3.eth.gas_price or 1_000_000,
        })
        signed = w3.eth.account.sign_transaction(tx, key)
        # eth-account 0.11 (web3 6.x) uses rawTransaction; 0.13+ uses raw_transaction
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=60)
        tx_hex = h.hex()
        if receipt.status == 1:
            log.info(f"[ERC8004Rep] wrote skill={skill_bps}bps "
                     f"directional={directional_pct}% tx={tx_hex}")
            return tx_hex
        log.warning(f"[ERC8004Rep] tx reverted: {tx_hex}")
    except Exception as e:
        log.debug(f"[ERC8004Rep] failed: {e}")
    return None
