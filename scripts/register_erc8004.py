#!/usr/bin/env python3
"""
scripts/register_erc8004.py — register Arke as an ERC-8004 agent on Arc testnet.

Mints an Identity NFT on the ERC-8004 Identity Registry with a tokenURI pointing
at the public agent card. Writes the minted agent id + tx hash to
`deploy/erc8004_agent.txt`.

If ERC8004_REGISTRY_ADDRESS is not configured, prints instructions and exits 0
(the operator supplies the registry address in Run 2 §ACTIVATE-7).

Usage:
    python scripts/register_erc8004.py [--registry <address>]
"""

import os
import sys
from pathlib import Path

TOKEN_URI = "https://arke.live/.well-known/agent-registration.json"
AGENT_FILE = Path(__file__).resolve().parent.parent / "deploy" / "erc8004_agent.txt"

# Minimal Identity Registry ABI fragment — just the mint entrypoint.
REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "tokenURI", "type": "string"}],
        "name": "register",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

INSTRUCTIONS = """\
ERC8004_REGISTRY_ADDRESS is not set.

Run 2 / §ACTIVATE-7 — provide the ERC-8004 Identity Registry address on Arc
testnet, then re-run:

    python scripts/register_erc8004.py --registry 0xYOUR_REGISTRY_ADDRESS
    # or set ERC8004_REGISTRY_ADDRESS in .env

This mints an Identity NFT whose tokenURI is:
    %s

If no registry is deployed on Arc testnet yet, deploy the canonical ERC-8004
Identity Registry first (see §ACTIVATE-7), then pass its address here.
""" % TOKEN_URI


def _parse_registry(argv) -> str:
    """--registry <addr> overrides ERC8004_REGISTRY_ADDRESS."""
    if "--registry" in argv:
        i = argv.index("--registry")
        if i + 1 < len(argv):
            return argv[i + 1]
    return os.getenv("ERC8004_REGISTRY_ADDRESS", "")


def register(registry_address: str) -> tuple[int, str]:
    """Mint the Identity NFT. Returns (agent_id, tx_hash). Requires web3 + key."""
    from web3 import Web3

    rpc = os.getenv("ARC_RPC_URL", "https://rpc.testnet.arc.network")
    key = os.getenv("ARC_PRIVATE_KEY", "")
    if not key:
        raise RuntimeError("ARC_PRIVATE_KEY not set")

    w3 = Web3(Web3.HTTPProvider(rpc))
    account = w3.eth.account.from_key(key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(registry_address),
        abi=REGISTRY_ABI,
    )

    fn = contract.functions.register(TOKEN_URI)

    # Best-effort: simulate the call to read the returned agent id.
    agent_id = 0
    try:
        agent_id = int(fn.call({"from": account.address}))
    except Exception:
        pass

    try:
        gas = int(fn.estimate_gas({"from": account.address}) * 1.3)
    except Exception:
        gas = 500_000

    tx = fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": gas,
        "gasPrice": w3.eth.gas_price or 1_000_000,
    })
    signed = account.sign_transaction(tx)
    # eth-account 0.11 (web3 6.x) uses rawTransaction; 0.13+ uses raw_transaction
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"registration tx reverted onchain: {tx_hash.hex()}")
    return agent_id, tx_hash.hex()


def write_agent_file(agent_id: int, tx: str, path: Path = None) -> Path:
    path = Path(path) if path else AGENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"agent_id={agent_id}\ntx={tx}\n")
    return path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    registry = _parse_registry(argv)
    if not registry:
        print(INSTRUCTIONS)
        return 0

    try:
        agent_id, tx = register(registry)
    except Exception as e:
        print(f"ERROR: registration failed: {e}")
        return 1

    write_agent_file(agent_id, tx)
    print(f"Agent registered. ID: {agent_id}, tx: {tx}")
    print(f"Wrote {AGENT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
