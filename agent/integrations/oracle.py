"""
agent/integrations/oracle.py — Onchain oracle integration

Logs Arke predictions to PredictionMarketOracle on Arc testnet.
Called after every successful post to create immutable record.
"""

import os
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _get_web3_and_contract():
    """Initialize Web3 connection to Arc testnet."""
    try:
        from web3 import Web3
    except ImportError:
        return None, None

    rpc_url = os.getenv("ARC_RPC_URL", "https://rpc.arc-testnet.canteen.xyz")
    contract_address = os.getenv("ORACLE_CONTRACT_ADDRESS", "")

    if not contract_address:
        return None, None

    abi_path = Path("deploy/oracle_abi.json")
    if not abi_path.exists():
        log.warning("[Oracle] ABI file not found at deploy/oracle_abi.json")
        return None, None

    with open(abi_path) as f:
        abi = json.load(f)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        log.warning(f"[Oracle] Cannot connect to {rpc_url}")
        return None, None

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_address),
        abi=abi
    )
    return w3, contract


def log_prediction_onchain(
    condition_id: str,
    question: str,
    market_pct: int,
    arke_pct: int,
) -> str:
    """
    Log a prediction to the onchain oracle.
    Returns transaction hash or empty string on failure.
    Fails silently — never blocks the posting pipeline.
    """
    private_key = os.getenv("ARC_PRIVATE_KEY", "")
    if not private_key:
        log.debug("[Oracle] ARC_PRIVATE_KEY not set — skipping onchain log")
        return ""

    try:
        from web3 import Web3
        w3, contract = _get_web3_and_contract()
        if not w3 or not contract:
            return ""

        account = w3.eth.account.from_key(private_key)

        # Convert condition_id to bytes32
        cid = condition_id[:66] if condition_id.startswith("0x") else f"0x{condition_id}"
        cid_padded = cid.ljust(66, "0")[:66]
        cid_bytes = bytes.fromhex(cid_padded[2:])

        tx = contract.functions.logPrediction(
            cid_bytes,
            question[:200],  # cap length for gas
            min(100, max(0, market_pct)),
            min(100, max(0, arke_pct)),
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 200_000,
            "gasPrice": w3.eth.gas_price,
        })

        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        tx_hex = tx_hash.hex()
        log.info(f"[Oracle] Logged onchain: {tx_hex}")
        return tx_hex

    except Exception as e:
        log.warning(f"[Oracle] Failed to log onchain: {e} — continuing")
        return ""
