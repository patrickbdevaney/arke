import { NextResponse } from "next/server";

export const revalidate = 60; // 1 minute cache

type GammaMarket = {
    conditionId?: string;
    question?: string;
    slug?: string;
    lastTradePrice?: number | string;
    volume24hr?: number | string;
    volume?: number | string;
    spread?: number | string;
    endDateIso?: string;
    events?: Array<{ slug?: string }>;
};

const SPORTS = [
    "vs.", "vs ", "NBA", "NFL", "MLB", "NHL", "UFC", "PGA",
    "FIFA", "Premier League", "La Liga", "Serie A", "Bundesliga",
    "Ligue 1", "Champions League", "Toulouse", "Marseille", "Lyon",
    "Monaco", "LoL", "CS2", "Valorant", "Dota", "Eurovision",
    "Wimbledon", "Roland Garros", "Masters", "Formula 1", "F1 ",
    "Grand Prix", "MLS", "cricket", "rugby", "Celtics", "Lakers",
    "Warriors", "Knicks", "Yankees", "Cubs", "Dodgers",
];

function isSports(q: string): boolean {
    return SPORTS.some(kw => q.toLowerCase().includes(kw.toLowerCase()));
}

export async function GET() {
    const builderAddr = process.env.POLY_BUILDER_ADDRESS ?? "";
    if (!builderAddr) {
        console.warn("[Intelligence] POLY_BUILDER_ADDRESS not set — bet URLs missing attribution");
    }

    // Fetch live Gamma feed
    let markets: GammaMarket[] = [];
    try {
        const r = await fetch(
            "https://gamma-api.polymarket.com/markets?active=true&limit=200&order=volume24hr&ascending=false",
            { next: { revalidate: 60 } }
        );
        if (r.ok) markets = (await r.json()) as GammaMarket[];
    } catch {}

    const now = new Date();

    const intelligence = markets
        .filter((m) => {
            const vol = Number(m.volume24hr ?? 0);
            const price = Number(m.lastTradePrice ?? 0);
            const pct = Math.round(price * 100);
            const q = m.question ?? "";
            if (vol < 15_000 || pct < 15 || pct > 85) return false;
            if (isSports(q)) return false;
            if (m.endDateIso && new Date(m.endDateIso) < now) return false;
            return true;
        })
        .sort((a, b) => Number(b.volume24hr ?? 0) - Number(a.volume24hr ?? 0))
        .slice(0, 30)
        .map((m) => {
            const pct = Math.round(Number(m.lastTradePrice ?? 0) * 100);
            const vol = Number(m.volume24hr ?? 0);
            const eventSlug = m.events?.[0]?.slug ?? m.slug ?? "";
            const ref = builderAddr ? `?ref=${builderAddr}` : "";
            const spread = Number(m.spread ?? 0);

            // Liquidity quality score: lower spread relative to volume = deeper
            const liquidityScore =
                vol > 100_000 && spread < 0.03 ? "deep"
              : vol > 50_000  && spread < 0.06 ? "moderate"
              : "thin";

            return {
                conditionId: m.conditionId ?? "",
                question: m.question ?? "",
                probabilityPct: pct,
                volume24hr: vol,
                volumeTotal: Number(m.volume ?? 0),
                endDateIso: m.endDateIso ?? "",
                spread,
                liquidityScore,
                betUrl: `polymarket.com/event/${eventSlug}${ref}`,
                eventSlug,
                // Arke intelligence fields — populated from db when available
                arkeEstimatePct: null,
                divergencePts: null,
                arkePosition: null,
                newsContext: null,
                tweetUrl: null,
                qualityScore: null,
                postedAt: null,
            };
        });

    return NextResponse.json({
        markets: intelligence,
        totalMarkets: intelligence.length,
        builderAddr,
        generatedAt: new Date().toISOString(),
    });
}
