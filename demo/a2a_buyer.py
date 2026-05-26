"""
demo/a2a_buyer.py — agent-to-agent demo: a buyer agent calls Arke over MCP and
pays sub-cent USDC for premium intelligence.

Standalone. NOT part of the agent loop. It:
  1. Spawns the Arke MCP server as a subprocess over stdio and connects as an
     MCP client.
  2. Calls a FREE tool (get_latest_call) and prints the result.
  3. Calls a PAID tool (get_market_intelligence) WITHOUT payment -> receives the
     402 challenge -> signs an EIP-3009 TransferWithAuthorization with
     TEST_BUYER_PRIVATE_KEY -> retries WITH the payment -> prints the unlocked
     intelligence (or the facilitator's decline reason).

Fail-safe: if CIRCLE_GATEWAY_FACILITATOR_URL or TEST_BUYER_PRIVATE_KEY is unset,
the paid path is skipped with a clear message and the script still demonstrates
the free tool — it never hard-fails during a dry run.

Run (from the repo root):
    python demo/a2a_buyer.py
"""

import os
import sys
import json
import time
import base64
import asyncio
import secrets
from pathlib import Path

# Repo root so `python -m agent.mcp_server` is importable when we spawn it.
REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ARC_CHAIN_ID = int(os.getenv("ARC_CHAIN_ID", "5042002"))
NETWORK = f"eip155:{ARC_CHAIN_ID}"
USDC_DECIMALS = 6


# ------------------------------------------------------------------ #
# Transcript helpers                                                  #
# ------------------------------------------------------------------ #


def banner(title: str):
    line = "═" * 64
    print(f"\n{line}\n  {title}\n{line}")


def show(label: str, obj):
    print(f"\n{label}:")
    print(json.dumps(obj, indent=2)[:1600])


def _parse_tool_result(result) -> dict:
    """Extract the JSON dict a FastMCP tool returned from a CallToolResult."""
    # Newer MCP servers also expose .structuredContent.
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        # FastMCP wraps non-dict returns under {"result": ...}; dicts pass through.
        return sc.get("result", sc) if "result" in sc and len(sc) == 1 else sc
    content = getattr(result, "content", None) or []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}
    return {}


# ------------------------------------------------------------------ #
# EIP-3009 authorization signing (x402 "exact" EVM scheme)            #
# ------------------------------------------------------------------ #


def _atomic(price_usdc: str) -> int:
    try:
        return int(round(float(price_usdc) * (10 ** USDC_DECIMALS)))
    except Exception:
        return 0


def build_payment(challenge: dict, private_key: str) -> str | None:
    """Sign an EIP-3009 TransferWithAuthorization and return the base64 X-PAYMENT
    header value (an x402 v2 PaymentPayload). Returns None if signing isn't
    possible. Never raises."""
    try:
        from eth_account import Account
    except Exception as e:
        print(f"  [skip] eth_account unavailable: {e}")
        return None

    try:
        accepts = (challenge.get("accepts") or [{}])[0]
        price = str(challenge.get("price") or accepts.get("maxAmountRequired") or "0.01")
        pay_to = challenge.get("payTo") or accepts.get("payTo") or ""
        # USDC contract on Arc testnet = EIP-712 verifyingContract. Operator pins
        # it; without it the signature can't match the real token domain.
        verifying_contract = os.getenv("CIRCLE_GATEWAY_USDC_ASSET", "")
        if not verifying_contract:
            print("  [skip] CIRCLE_GATEWAY_USDC_ASSET (USDC contract) not set — "
                  "cannot build a domain-correct EIP-3009 signature")
            return None

        acct = Account.from_key(private_key)
        value = _atomic(price)
        now = int(time.time())
        valid_after = "0"
        valid_before = str(now + 600)
        nonce = "0x" + secrets.token_hex(32)

        authorization = {
            "from": acct.address,
            "to": pay_to,
            "value": str(value),
            "validAfter": valid_after,
            "validBefore": valid_before,
            "nonce": nonce,
        }

        typed = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ],
            },
            "primaryType": "TransferWithAuthorization",
            "domain": {
                "name": os.getenv("CIRCLE_GATEWAY_USDC_NAME", "USDC"),
                "version": os.getenv("CIRCLE_GATEWAY_USDC_VERSION", "2"),
                "chainId": ARC_CHAIN_ID,
                "verifyingContract": verifying_contract,
            },
            "message": {
                "from": acct.address,
                "to": pay_to,
                "value": value,
                "validAfter": int(valid_after),
                "validBefore": int(valid_before),
                "nonce": bytes.fromhex(nonce[2:]),
            },
        }

        signed = Account.sign_typed_data(private_key, full_message=typed)
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        payload = {
            "x402Version": 2,
            "scheme": "exact",
            "network": NETWORK,
            "payload": {"signature": signature, "authorization": authorization},
        }
        return base64.b64encode(json.dumps(payload).encode()).decode()
    except Exception as e:
        print(f"  [skip] could not build payment: {e}")
        return None


# ------------------------------------------------------------------ #
# Main demo flow                                                      #
# ------------------------------------------------------------------ #


async def run():
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agent.mcp_server"],
        env=os.environ.copy(),
        cwd=str(REPO_ROOT),
    )

    banner("A2A DEMO — buyer agent calls Arke over MCP")
    print("Spawning the Arke MCP server as a stdio subprocess...")

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"Connected. Arke exposes {len(names)} tools: {', '.join(names)}")

            # ---- 1. FREE tool ----
            banner("STEP 1 — call a FREE tool: get_latest_call")
            latest = _parse_tool_result(
                await session.call_tool("get_latest_call", {})
            )
            show("Arke's latest call (free)", latest)

            condition_id = latest.get("condition_id") or os.getenv(
                "DEMO_CONDITION_ID", ""
            )

            # ---- 2. PAID tool, no payment -> 402 ----
            banner("STEP 2 — call a PAID tool with NO payment: get_market_intelligence")
            challenge = _parse_tool_result(
                await session.call_tool(
                    "get_market_intelligence", {"condition_id": condition_id}
                )
            )
            show("402 challenge (payment required)", challenge)

            # ---- 3. Decide whether we can demo the paid path ----
            facilitator = os.getenv("CIRCLE_GATEWAY_FACILITATOR_URL", "")
            buyer_key = os.getenv("TEST_BUYER_PRIVATE_KEY", "")

            if not facilitator or not buyer_key:
                banner("STEP 3 — paid path skipped")
                missing = []
                if not facilitator:
                    missing.append("CIRCLE_GATEWAY_FACILITATOR_URL")
                if not buyer_key:
                    missing.append("TEST_BUYER_PRIVATE_KEY")
                print("Paid path skipped — set Gateway env to demo payment.")
                print(f"  Missing: {', '.join(missing)}")
                print("\nThe free tool worked and the paid tool correctly returned a")
                print("402 challenge. Set the Gateway env (local, never committed) to")
                print("sign an EIP-3009 authorization and unlock the paid response.")
                return

            # ---- 3b. Sign EIP-3009 and retry WITH payment ----
            banner("STEP 3 — sign EIP-3009 authorization and retry WITH payment")
            payment = build_payment(challenge, buyer_key)
            if not payment:
                print("Could not build a payment — paid path skipped (no hard fail).")
                return
            print(f"Signed X-PAYMENT built ({len(payment)} b64 chars). Retrying...")

            unlocked = _parse_tool_result(
                await session.call_tool(
                    "get_market_intelligence",
                    {"condition_id": condition_id, "payment": payment},
                )
            )
            if unlocked.get("payment_required"):
                banner("RESULT — facilitator declined the payment")
                print("The Gateway facilitator did not accept the authorization.")
                show("Response", unlocked)
            else:
                banner("RESULT — paid intelligence unlocked")
                show("Full market intelligence (paid)", unlocked)


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # Never hard-fail the demo — print and exit cleanly so a recording
        # always shows a graceful ending.
        print(f"\n[demo error, exiting cleanly] {e}")


if __name__ == "__main__":
    main()
