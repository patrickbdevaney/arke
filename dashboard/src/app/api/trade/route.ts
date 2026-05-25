import { NextRequest, NextResponse } from "next/server";

// User-signed orders are forwarded to the Polymarket CLOB verbatim. The builder
// attribution is part of the SIGNED EIP-712 order, so it is set + signed client
// side (NEXT_PUBLIC_POLY_BUILDER_CODE) — rewriting it here would change the hash
// and invalidate the user's signature. The builder code is public (a keccak-
// encoded address), not a key. This route never holds a private key — the user
// already signed the order in their wallet.

const CLOB_ORDER_URL = "https://clob.polymarket.com/order";

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

        // Forward exactly what was signed — see the note above on why the builder
        // field can't be rewritten here.
        const resp = await fetch(CLOB_ORDER_URL, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ order, signature, owner }),
        });
        const data = await resp.json();
        return NextResponse.json(data, { status: resp.status });
    } catch (e: unknown) {
        return NextResponse.json({ error: errText(e) }, { status: 500 });
    }
}
