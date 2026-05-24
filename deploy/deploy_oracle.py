"""
deploy/deploy_oracle.py — Deploy PredictionMarketOracle to Arc testnet
Usage:
    python deploy/deploy_oracle.py
Requires:
    pip install web3 py-solc-x
    CIRCLE_WALLET_ADDRESS in .env (agent wallet)
    ARC_RPC_URL in .env
    ARC_PRIVATE_KEY in .env (deployer key)
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()


def compile_and_deploy():
    try:
        from web3 import Web3
        from solcx import compile_standard, install_solc
    except ImportError:
        print("Installing dependencies...")
        import subprocess

        subprocess.run(["pip", "install", "web3", "py-solc-x", "-q"])
        from web3 import Web3
        from solcx import compile_standard, install_solc

    install_solc("0.8.19")

    rpc_url = (
        os.getenv("ARC_RPC_PRIMARY")
        or os.getenv("ARC_RPC_FALLBACK")
        or os.getenv("ARC_RPC_URL")
        or "https://rpc.testnet.arc.network"
    )
    private_key = os.getenv("ARC_PRIVATE_KEY", "")
    agent_address = os.getenv("CIRCLE_WALLET_ADDRESS", "")

    if not private_key:
        print("ERROR: ARC_PRIVATE_KEY not set in .env")
        print("This is the deployer wallet private key for Arc testnet")
        return

    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        print(f"ERROR: Cannot connect to Arc testnet at {rpc_url}")
        print("Check ARC_RPC_URL in .env")
        return

    print(f"Connected to Arc testnet")
    print(f"Chain ID: {w3.eth.chain_id}")

    with open("contracts/PredictionMarketOracle.sol", "r") as f:
        source = f.read()

    compiled = compile_standard(
        {
            "language": "Solidity",
            "sources": {"PredictionMarketOracle.sol": {"content": source}},
            "settings": {"outputSelection": {"*": {"*": ["abi", "evm.bytecode"]}}},
        },
        solc_version="0.8.19",
    )

    contract_data = compiled["contracts"]["PredictionMarketOracle.sol"][
        "PredictionMarketOracle"
    ]
    abi = contract_data["abi"]
    bytecode = contract_data["evm"]["bytecode"]["object"]

    account = w3.eth.account.from_key(private_key)
    print(f"Deployer: {account.address}")
    print(f"Balance: {w3.eth.get_balance(account.address)} wei")

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    gas_price = w3.eth.gas_price or 1_000_000

    tx = contract.constructor(agent_address or account.address).build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 2_000_000,
            "gasPrice": gas_price,
        }
    )

    signed = account.sign_transaction(tx)

    # web3 v6 uses raw_transaction; v5 uses rawTransaction — handle both
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)

    print(f"Deploying... tx: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    contract_address = receipt["contractAddress"]

    print(f"\nOracle deployed at: {contract_address}")
    print(f"Arc explorer: https://testnet.arcscan.app/address/{contract_address}")

    # Save ABI and address
    os.makedirs("deploy", exist_ok=True)
    with open("deploy/oracle_abi.json", "w") as f:
        json.dump(abi, f, indent=2)
    with open("deploy/oracle_address.txt", "w") as f:
        f.write(contract_address)

    print(f"\nSaved to deploy/oracle_abi.json and deploy/oracle_address.txt")
    print(f"Add to .env: ORACLE_CONTRACT_ADDRESS={contract_address}")
    return contract_address


if __name__ == "__main__":
    compile_and_deploy()
