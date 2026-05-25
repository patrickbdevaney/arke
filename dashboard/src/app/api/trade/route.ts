import { NextRequest, NextResponse } from "next/server";

// User-signed orders are forwarded to the Polymarket CLOB with Arke's builder
// code injected SERVER-SIDE. The builder code is never exposed to the browser
// (no NEXT_PUBLIC_) and can't be stripped or swapped client-side. This route
// never holds a private key — the user already signed the order in their wallet.

const CLOB_ORDER_URL = "https://clob.polymarket.com/order";
const BUILDER_CODE   = (process.env.POLY_BUILDER_CODE ?? "").replace(/^0x/, "")
                           .padEnd(64, "0").slice(0, 64);

// A thrown value may be a plain object, not an Error — String() on those yields
// "[object Object]". Extract a readable message before falling back.
function errText(e: unknown): string {
    if (e instanceof Error) return e.message;
    if (typeof e === "string") return e;
    if (e && typeof e === "object") {
        const o = e as Record<string, unknown>;
        if (typeof o.message === "string") return o.message;
        if (typeof o.reason  === "string") return o.reason;
        try { return JSON.stringify(e); } catch { /* fall through */ }
    }
    return String(e);
}

export async function POST(req: NextRequest) {
    try {
        const { order, signature, owner } = await req.json();
        if (!order || !signature || !owner)
            return NextResponse.json({ error: "missing fields" }, { status: 400 });

        // Inject builder code server-side — can't be stripped client-side
        const enriched = { ...order, builder: "0x" + BUILDER_CODE };

        const resp = await fetch(CLOB_ORDER_URL, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ order: enriched, signature, owner }),
        });
        const data = await resp.json();
        return NextResponse.json(data, { status: resp.status });
    } catch (e: unknown) {
        return NextResponse.json({ error: errText(e) }, { status: 500 });
    }
}
