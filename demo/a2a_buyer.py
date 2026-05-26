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


# Circle's verified GatewayWalletBatched scheme (GET /v1/x402/supported): the
# buyer signs an EIP-712 TransferWithAuthorization against the GatewayWallet
# contract domain (name "GatewayWalletBatched", version "1"), NOT the USDC token.
GATEWAY_WALLET_DEFAULT = "0x0077777d7eba4688bdef3e311b846f25870a19b9"


def build_payment(challenge: dict, private_key: str, resource: str) -> str | None:
    """Build an x402 v2 PaymentPayload for Circle's GatewayWalletBatched "exact"
    scheme and return it base64-encoded (the X-PAYMENT header value). Returns
    None if signing isn't possible. Never raises.

    The payload includes `resource`, `accepted` (the chosen requirements), and
    `payload.{signature,authorization}` — the exact shape the live facilitator
    validates. The authorization is a standard EIP-3009 field set, but signed
    under the GatewayWallet domain advertised in the challenge's `extra`."""
    try:
        from eth_account import Account
    except Exception as e:
        print(f"  [skip] eth_account unavailable: {e}")
        return None

    try:
        accepts = (challenge.get("accepts") or [{}])[0]
        extra = accepts.get("extra") or {}
        price = str(challenge.get("price") or accepts.get("maxAmountRequired") or "0.01")
        pay_to = accepts.get("payTo") or challenge.get("payTo") or ""

        # verifyingContract = the GatewayWallet (from the challenge, else env/default).
        verifying_contract = (
            extra.get("verifyingContract")
            or os.getenv("CIRCLE_GATEWAY_WALLET_CONTRACT")
            or GATEWAY_WALLET_DEFAULT
        )
        domain_name = extra.get("name", "GatewayWalletBatched")
        domain_version = str(extra.get("version", "1"))

        acct = Account.from_key(private_key)
        value = _atomic(price)
        now = int(time.time())
        valid_after = "0"
        # Honour the scheme's minValiditySeconds (604800 = 7d) with headroom.
        valid_before = str(now + 700000)
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
                "name": domain_name,
                "version": domain_version,
                "chainId": ARC_CHAIN_ID,
                "verifyingContract": verifying_contract,
            },
            "message": {
                "from": acct.address,
                "to": pay_to,
                "value": int(value),
                "validAfter": int(valid_after),
                "validBefore": int(valid_before),
                "nonce": bytes.fromhex(nonce[2:]),
            },
        }
        print(f"  signing TransferWithAuthorization under domain "
              f"{domain_name} v{domain_version} @ {verifying_contract}")

        signed = Account.sign_typed_data(private_key, full_message=typed)
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        # Full x402 v2 PaymentPayload (resource + accepted + payload), the shape
        # the facilitator's /verify requires.
        feed_base = os.getenv("ARKE_FEED_BASE", "https://feed.arke.live").rstrip("/")
        payload = {
            "x402Version": 2,
            "scheme": "exact",
            "network": NETWORK,
            "resource": {
                "url": f"{feed_base}/mcp/{resource}",
                "description": f"Arke MCP tool: {resource}",
                "mimeType": "application/json",
            },
            "accepted": accepts,
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
            payment = build_payment(challenge, buyer_key, resource="get_market_intelligence")
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
