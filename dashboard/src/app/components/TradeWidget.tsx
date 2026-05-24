"use client";
import { useState } from "react";

const EXCHANGE_ADDR    = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E";
const POLYGON_CHAIN_ID = 137;

type Side  = "YES" | "NO";
type Phase = "idle" | "connecting" | "signing" | "submitting" | "success" | "error";

type Props = {
    tokenId:      string;
    question:     string;
    marketPct:    number;
    arkeEstimate: number;
    betUrl:       string;  // plain-link fallback
};

export function TradeWidget({ tokenId, marketPct, arkeEstimate, betUrl }: Props) {
    const [phase,   setPhase]   = useState<Phase>("idle");
    const [sizeStr, setSizeStr] = useState("5");
    const [side,    setSide]    = useState<Side>(arkeEstimate > marketPct ? "YES" : "NO");
    const [txHash,  setTxHash]  = useState("");
    const [errMsg,  setErrMsg]  = useState("");

    const hasWallet = typeof window !== "undefined" && !!(window as any).ethereum;

    const fallback = (
        <a href={`https://${betUrl}`} target="_blank" rel="noopener noreferrer"
           className="text-xs text-amber-600 hover:text-amber-400 font-data">
            Trade on Polymarket ▸
        </a>
    );

    async function handleTrade() {
        const size = parseFloat(sizeStr);
        if (!size || size <= 0) return;
        setPhase("connecting"); setErrMsg("");
        try {
            const eth = (window as any).ethereum;

            // 1. Connect wallet
            const accounts: string[] = await eth.request({ method: "eth_requestAccounts" });
            const maker = accounts[0];

            // 2. Switch to Polygon if needed
            const chainHex = await eth.request({ method: "eth_chainId" });
            if (parseInt(chainHex, 16) !== POLYGON_CHAIN_ID) {
                await eth.request({
                    method: "wallet_switchEthereumChain",
                    params: [{ chainId: "0x89" }],
                });
            }

            // 3. Build order struct — mirrors polymarket_stake.py exactly
            const makerAmt = Math.round(size * 1_000_000);
            const takerAmt = Math.round((size / 0.99) * 1_000_000);
            const order = {
                salt:        Date.now().toString(),
                maker, signer: maker,
                taker:       "0x0000000000000000000000000000000000000000",
                tokenId,
                makerAmount: makerAmt.toString(),
                takerAmount: takerAmt.toString(),
                expiration:  "0",
                nonce:       "0",
                feeRateBps:  "0",
                side:        side === "YES" ? 0 : 1,
                signatureType: 0,
                // builder injected server-side in /api/trade; zeros here
                builder:     "0x" + "0".repeat(64),
            };

            // EIP-712 typed data — same domain as the Python side
            const typedData = {
                types: {
                    EIP712Domain: [
                        { name: "name",              type: "string"  },
                        { name: "version",           type: "string"  },
                        { name: "chainId",           type: "uint256" },
                        { name: "verifyingContract", type: "address" },
                    ],
                    Order: [
                        { name: "salt",          type: "uint256" },
                        { name: "maker",         type: "address" },
                        { name: "signer",        type: "address" },
                        { name: "taker",         type: "address" },
                        { name: "tokenId",       type: "uint256" },
                        { name: "makerAmount",   type: "uint256" },
                        { name: "takerAmount",   type: "uint256" },
                        { name: "expiration",    type: "uint256" },
                        { name: "nonce",         type: "uint256" },
                        { name: "feeRateBps",    type: "uint256" },
                        { name: "side",          type: "uint8"   },
                        { name: "signatureType", type: "uint8"   },
                        { name: "builder",       type: "bytes32" },
                    ],
                },
                primaryType: "Order",
                domain: {
                    name: "Polymarket CTF Exchange", version: "1",
                    chainId: POLYGON_CHAIN_ID,
                    verifyingContract: EXCHANGE_ADDR,
                },
                message: {
                    ...order,
                    tokenId:    parseInt(tokenId),
                    makerAmount: makerAmt,
                    takerAmount: takerAmt,
                    expiration: 0, nonce: 0, feeRateBps: 0,
                    builder:    "0x" + "0".repeat(64),
                },
            };

            // 4. User signs in their wallet — no key ever touches the server
            setPhase("signing");
            const signature: string = await eth.request({
                method: "eth_signTypedData_v4",
                params: [maker, JSON.stringify(typedData)],
            });

            // 5. Submit via /api/trade — server injects builder code bytes32
            setPhase("submitting");
            const res  = await fetch("/api/trade", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ order, signature, owner: maker }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error ?? "order rejected");
            setTxHash(data.orderHash ?? data.orderID ?? data.id ?? "submitted");
            setPhase("success");
        } catch (e: unknown) {
            setErrMsg(e instanceof Error ? e.message : String(e));
            setPhase("error");
        }
    }

    if (!hasWallet) return fallback;

    if (phase === "success") return (
        <div className="text-xs font-data text-green-400 mt-2">
            ✓ Order submitted
            {txHash && <span className="text-neutral-500"> · {txHash.slice(0,16)}…</span>}
            <div className="text-neutral-600 mt-0.5">
                0.5% builder fee attributed to Arke on this fill
            </div>
        </div>
    );

    return (
        <div className="mt-2 border-t border-neutral-800 pt-2 space-y-1.5">
            <div className="flex items-center gap-2">
                {(["YES", "NO"] as Side[]).map(s => (
                    <button key={s} onClick={() => setSide(s)}
                        className={`text-xs px-2 py-0.5 border font-data transition-colors ${
                            side === s
                                ? s === "YES"
                                    ? "border-green-600 text-green-400 bg-green-950"
                                    : "border-blue-600 text-blue-400 bg-blue-950"
                                : "border-neutral-700 text-neutral-500 hover:border-neutral-500"
                        }`}>
                        {s}
                    </button>
                ))}
                <input
                    type="number" min="1" step="1" value={sizeStr}
                    onChange={e => setSizeStr(e.target.value)}
                    className="w-16 text-xs font-data bg-neutral-900 border
                               border-neutral-700 text-neutral-200 px-1 py-0.5
                               text-right focus:outline-none focus:border-amber-600"
                />
                <span className="text-xs text-neutral-600 font-data">USDC</span>
            </div>

            {phase === "error" && (
                <div className="text-xs text-red-400 font-data truncate">{errMsg}</div>
            )}

            <div className="flex items-center gap-3">
                <button
                    onClick={handleTrade}
                    disabled={phase !== "idle" && phase !== "error"}
                    className="text-xs font-data px-3 py-1 border border-amber-600
                               text-amber-400 hover:bg-amber-950 disabled:opacity-40
                               disabled:cursor-not-allowed transition-colors">
                    {phase === "idle" || phase === "error" ? "Trade ▸"
                     : phase === "connecting"              ? "connecting…"
                     : phase === "signing"                 ? "sign in wallet…"
                     : phase === "submitting"              ? "submitting…"
                     : "…"}
                </button>
                {fallback}
            </div>
            <div className="text-xs text-neutral-700 font-data">
                0.5% builder fee on fills · attributed to Arke
            </div>
        </div>
    );
}
