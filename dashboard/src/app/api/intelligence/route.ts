import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";

export const revalidate = 60; // 1 minute cache

// ── Public types ─────────────────────────────────────────────────────
// Missing values are typed `null` (never `undefined`) so JSON serialization
// is predictable for the dashboard.

export type TrackRecordCall = {
    conditionId: string;
    question: string | null;
    arkeProbability: number | null;
    marketProbability: number | null;
    divergenceBps: number | null;
    arkeCall: "YES" | "NO" | null;
    reasoningCid: string | null;
    resolved: boolean;
    outcome: "YES" | "NO" | null;
    wasCorrect: boolean | null;
    oracleLogTx: string | null;
    oracleResolveTx: string | null;
    stakeTx: string | null;
    postedAt: string | null;
    xPostUrl: string | null;
};

export type TrackRecordSummary = {
    nTotal: number;
    nResolved: number;
    accuracyPct: number;
    brierIndex: number;
    operatingSince: string;
};

export type MarketIntelligence = {
    conditionId: string;
    question: string;
    probabilityPct: number;
    volume24hr: number;
    volumeTotal: number;
    endDateIso: string;
    spread: number;
    liquidityScore: "deep" | "moderate" | "thin";
    betUrl: string;
    eventSlug: string;
    // Arke intelligence — merged from the track record by conditionId
    arkeEstimatePct: number | null;
    divergencePts: number | null;
    arkePosition: "AGREE" | "BULL" | "BEAR" | "DISAGREE" | "NEUTRAL" | null;
    newsContext: string | null;
    councilForecast: string | null;
    tweetUrl: string | null;
    qualityScore: number | null;
    postedAt: string | null;
    resolved: boolean | null;
    wasCorrect: boolean | null;
    oracleLogTx: string | null;
    oracleResolveTx: string | null;
    stakeTx: string | null;
    reasoningCid: string | null;
};

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

// Raw call shape served by agent/feed_server.py (snake_case).
type FeedCall = {
    condition_id: string;
    question: string | null;
    arke_probability: number | null;
    market_probability: number | null;
    divergence_bps: number | null;
    arke_call: "YES" | "NO" | null;
    reasoning_cid: string | null;
    resolved: boolean;
    outcome: "YES" | "NO" | null;
    was_correct: boolean | null;
    oracle_log_tx: string | null;
    oracle_resolve_tx: string | null;
    stake_tx: string | null;
    posted_at: string | null;
    x_post_url: string | null;
};

type FeedResponse = {
    summary: {
        n_total: number;
        n_resolved: number;
        accuracy_pct: number;
        brier_index: number;
        source: string;
        oracle_contract: string | null;
        operating_since: string;
    };
    calls: FeedCall[];
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
    return SPORTS.some((kw) => q.toLowerCase().includes(kw.toLowerCase()));
}

function toCall(c: FeedCall): TrackRecordCall {
    return {
        conditionId: c.condition_id,
        question: c.question ?? null,
        arkeProbability: c.arke_probability ?? null,
        marketProbability: c.market_probability ?? null,
        divergenceBps: c.divergence_bps ?? null,
        arkeCall: c.arke_call ?? null,
        reasoningCid: c.reasoning_cid ?? null,
        resolved: Boolean(c.resolved),
        outcome: c.outcome ?? null,
        wasCorrect: c.was_correct ?? null,
        oracleLogTx: c.oracle_log_tx ?? null,
        oracleResolveTx: c.oracle_resolve_tx ?? null,
        stakeTx: c.stake_tx ?? null,
        postedAt: c.posted_at ?? null,
        xPostUrl: c.x_post_url ?? null,
    };
}

// Read the council's tweet text from the pinned reasoning trace, server-side.
// Trace files live in public/traces/{cid[:16]}.json and are bundled into the
// route's serverless function via experimental.outputFileTracingIncludes (see
// next.config.js). The "Bet: …" suffix is stripped — it's a call-to-action,
// not analysis. Any miss (no file, bad JSON, empty forecast) returns null so
// the card falls back to the plain @arke_ai link.
function readCouncilForecast(cid: string): string | null {
    if (!cid) return null;
    try {
        const file = path.join(
            process.cwd(),
            "public",
            "traces",
            `${cid.slice(0, 16)}.json`
        );
        const raw = fs.readFileSync(file, "utf8");
        const forecast = JSON.parse(raw)?.council_forecast;
        if (typeof forecast !== "string") return null;
        const text = forecast.split("Bet:")[0].trim();
        return text.length > 0 ? text : null;
    } catch {
        return null;
    }
}

// Server-side fetch of the paid feed. Uses the X-Internal bypass so no x402
// payment is needed for the dashboard's own calls. Degrades to null on any
// problem — the dashboard then shows Gamma-only data and never 500s.
async function fetchTrackRecord(): Promise<FeedResponse | null> {
    const base = process.env.ARKE_FEED_URL;
    if (!base) return null;
    try {
        const r = await fetch(`${base.replace(/\/$/, "")}/v1/arke/track-record`, {
            headers: {
                "X-Internal": "true",
                "X-Internal-Secret": process.env.INTERNAL_SECRET ?? "",
            },
            next: { revalidate: 60 },
        });
        if (!r.ok) return null;
        return (await r.json()) as FeedResponse;
    } catch {
        return null;
    }
}

export async function GET() {
    const builderAddr = process.env.POLY_BUILDER_ADDRESS ?? "";
    if (!builderAddr) {
        console.warn("[Intelligence] POLY_BUILDER_ADDRESS not set — bet URLs missing attribution");
    }

    // Fetch live Gamma feed + Arke track record concurrently.
    let markets: GammaMarket[] = [];
    const [gammaRes, feed] = await Promise.all([
        fetch(
            "https://gamma-api.polymarket.com/markets?active=true&limit=200&order=volume24hr&ascending=false",
            { next: { revalidate: 60 } }
        ).catch(() => null),
        fetchTrackRecord(),
    ]);
    try {
        if (gammaRes && gammaRes.ok) markets = (await gammaRes.json()) as GammaMarket[];
    } catch {}

    const calls: TrackRecordCall[] = (feed?.calls ?? []).map(toCall);
    const callsByCid = new Map<string, TrackRecordCall>();
    for (const c of calls) {
        if (c.conditionId && !callsByCid.has(c.conditionId)) callsByCid.set(c.conditionId, c);
    }

    const now = new Date();

    const intelligence: MarketIntelligence[] = markets
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
            const cid = m.conditionId ?? "";

            const liquidityScore =
                vol > 100_000 && spread < 0.03 ? "deep"
              : vol > 50_000  && spread < 0.06 ? "moderate"
              : "thin";

            const call = cid ? callsByCid.get(cid) ?? null : null;
            const councilForecast =
                call?.reasoningCid ? readCouncilForecast(cid) : null;
            const arkeEstimatePct = call?.arkeProbability ?? null;
            const divergencePts =
                arkeEstimatePct !== null ? arkeEstimatePct - pct : null;
            const arkePosition: MarketIntelligence["arkePosition"] =
                divergencePts === null ? null
              : Math.abs(divergencePts) <= 3 ? "AGREE"
              : divergencePts > 0 ? "BULL"
              : "BEAR";

            return {
                conditionId: cid,
                question: m.question ?? "",
                probabilityPct: pct,
                volume24hr: vol,
                volumeTotal: Number(m.volume ?? 0),
                endDateIso: m.endDateIso ?? "",
                spread,
                liquidityScore,
                betUrl: `polymarket.com/event/${eventSlug}${ref}`,
                eventSlug,
                arkeEstimatePct,
                divergencePts,
                arkePosition,
                newsContext: null,
                councilForecast,
                tweetUrl: call?.xPostUrl ?? null,
                qualityScore: null,
                postedAt: call?.postedAt ?? null,
                resolved: call ? call.resolved : null,
                wasCorrect: call?.wasCorrect ?? null,
                oracleLogTx: call?.oracleLogTx ?? null,
                oracleResolveTx: call?.oracleResolveTx ?? null,
                stakeTx: call?.stakeTx ?? null,
                reasoningCid: call?.reasoningCid ?? null,
            };
        });

    const trackRecord: TrackRecordSummary | null = feed
        ? {
            nTotal: feed.summary.n_total,
            nResolved: feed.summary.n_resolved,
            accuracyPct: feed.summary.accuracy_pct,
            brierIndex: feed.summary.brier_index,
            operatingSince: feed.summary.operating_since,
        }
        : null;

    return NextResponse.json({
        markets: intelligence,
        totalMarkets: intelligence.length,
        trackRecord,
        calls,
        oracleContract: feed?.summary.oracle_contract ?? null,
        builderAddr,
        generatedAt: new Date().toISOString(),
    });
}
