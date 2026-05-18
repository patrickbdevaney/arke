import { LiveIndicator } from "./components/LiveIndicator";

export const revalidate = 60;

type MarketIntelligence = {
    conditionId: string;
    question: string;
    probabilityPct: number;
    volume24hr: number;
    volumeTotal: number;
    endDateIso: string;
    spread: number;
    liquidityScore: "deep" | "moderate" | "thin";
    betUrl: string;
    arkeEstimatePct: number | null;
    divergencePts: number | null;
    arkePosition: "AGREE" | "DISAGREE" | "NEUTRAL" | null;
    newsContext: string | null;
    tweetUrl: string | null;
    qualityScore: number | null;
    postedAt: string | null;
};

async function getIntelligence(): Promise<MarketIntelligence[]> {
    const host = process.env.VERCEL_URL
        ? `https://${process.env.VERCEL_URL}`
        : "http://localhost:3000";
    try {
        const r = await fetch(`${host}/api/intelligence`, {
            next: { revalidate: 60 }
        });
        if (!r.ok) return [];
        const data = await r.json();
        return data.markets ?? [];
    } catch {
        return [];
    }
}

function LiquidityBadge({ score }: { score: string }) {
    const colors = {
        deep: "text-green-400 border-green-800",
        moderate: "text-amber-400 border-amber-800",
        thin: "text-red-400 border-red-800",
    };
    return (
        <span className={`text-xs border px-1 ${colors[score as keyof typeof colors] ?? colors.thin}`}>
            {score.toUpperCase()}
        </span>
    );
}

function PositionBadge({ position }: { position: string | null }) {
    if (!position || position === "NEUTRAL") return null;
    const isDisagree = position === "DISAGREE";
    return (
        <span className={`text-xs px-1 border font-bold ${
            isDisagree
                ? "text-red-400 border-red-800 bg-red-950"
                : "text-green-400 border-green-800 bg-green-950"
        }`}>
            ARKE {position}S
        </span>
    );
}

function MarketCard({ m }: { m: MarketIntelligence }) {
    const hasDivergence = m.divergencePts !== null;
    const divergenceColor = !hasDivergence ? ""
        : m.divergencePts! > 0 ? "text-green-400"
        : "text-red-400";
    const divergenceStr = !hasDivergence ? "—"
        : `${m.divergencePts! > 0 ? "+" : ""}${m.divergencePts}pts`;

    const daysLeft = m.endDateIso
        ? Math.max(0, Math.ceil(
            (new Date(m.endDateIso).getTime() - Date.now()) / 86_400_000
          ))
        : null;

    return (
        <a
            href={`https://${m.betUrl}`}
            target="_blank"
            rel="noopener noreferrer"
            className="block border border-neutral-800 bg-neutral-950 p-3 hover:border-amber-600 transition-colors"
        >
            {/* Header: badges */}
            <div className="flex items-center gap-2 mb-2 flex-wrap">
                <LiquidityBadge score={m.liquidityScore} />
                <PositionBadge position={m.arkePosition} />
                {daysLeft !== null && daysLeft <= 7 && (
                    <span className="text-xs text-red-400 border border-red-800 px-1">
                        {daysLeft}D LEFT
                    </span>
                )}
            </div>

            {/* Question */}
            <div className="text-sm text-neutral-200 leading-snug mb-3 font-mono">
                {m.question}
            </div>

            {/* Core data grid */}
            <div className="grid grid-cols-3 gap-2 text-xs font-mono mb-2">
                <div>
                    <div className="text-neutral-500 mb-0.5">MARKET</div>
                    <div className="text-green-400 text-xl font-bold tabular-nums">
                        {m.probabilityPct}%
                    </div>
                </div>
                <div>
                    <div className="text-neutral-500 mb-0.5">ARKE</div>
                    <div className="text-amber-400 text-xl font-bold tabular-nums">
                        {m.arkeEstimatePct !== null ? `${m.arkeEstimatePct}%` : "—"}
                    </div>
                </div>
                <div>
                    <div className="text-neutral-500 mb-0.5">EDGE</div>
                    <div className={`text-xl font-bold tabular-nums ${divergenceColor}`}>
                        {divergenceStr}
                    </div>
                </div>
            </div>

            {/* Volume and spread */}
            <div className="flex justify-between text-xs text-neutral-500 font-mono mb-2">
                <span>${(m.volume24hr / 1000).toFixed(0)}K/24h</span>
                <span>spread {(m.spread * 100).toFixed(1)}¢</span>
                <span>ends {m.endDateIso?.slice(0, 10) ?? "—"}</span>
            </div>

            {/* News context if available */}
            {m.newsContext && (
                <div className="text-xs text-neutral-500 border-t border-neutral-800 pt-2 mt-2 font-mono leading-relaxed">
                    📡 {m.newsContext.slice(0, 120)}
                    {m.newsContext.length > 120 ? "..." : ""}
                </div>
            )}

            {/* Tweet link if available */}
            {m.tweetUrl && (
                <div className="text-xs text-amber-600 mt-1 font-mono">
                    → @arke_ai analysis
                </div>
            )}
        </a>
    );
}

function StatsBar({ markets }: { markets: MarketIntelligence[] }) {
    const analyzed = markets.filter(m => m.arkeEstimatePct !== null);
    const disagreements = markets.filter(m => m.arkePosition === "DISAGREE");
    const deepLiquidity = markets.filter(m => m.liquidityScore === "deep");

    return (
        <header className="border-b border-neutral-800 bg-black sticky top-0 z-10">
            <div className="px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono">
                <span className="text-amber-400 font-bold tracking-widest">ARKE</span>
                <span className="text-neutral-600">|</span>
                <span>
                    <span className="text-green-400 tabular-nums">{markets.length}</span>
                    <span className="text-neutral-500"> MARKETS MONITORED</span>
                </span>
                <span className="text-neutral-600">|</span>
                <span>
                    <span className="text-amber-400 tabular-nums">{analyzed.length}</span>
                    <span className="text-neutral-500"> ANALYZED</span>
                </span>
                <span className="text-neutral-600">|</span>
                <span>
                    <span className="text-red-400 tabular-nums">{disagreements.length}</span>
                    <span className="text-neutral-500"> ARKE DISAGREES</span>
                </span>
                <span className="text-neutral-600">|</span>
                <span>
                    <span className="text-green-400 tabular-nums">{deepLiquidity.length}</span>
                    <span className="text-neutral-500"> DEEP LIQUIDITY</span>
                </span>
                <span className="text-neutral-600">|</span>
                <a
                    href="https://x.com/arke_ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-400 hover:text-amber-300"
                >
                    @arke_ai
                </a>
                <span className="ml-auto">
                    <LiveIndicator />
                </span>
            </div>
        </header>
    );
}

export default async function Page() {
    const markets = await getIntelligence();

    // Sort: Arke-analyzed and disagreements first, then by volume
    const sorted = [...markets].sort((a, b) => {
        const aHas = a.arkeEstimatePct !== null ? 1 : 0;
        const bHas = b.arkeEstimatePct !== null ? 1 : 0;
        if (aHas !== bHas) return bHas - aHas;
        const aDisagree = a.arkePosition === "DISAGREE" ? 1 : 0;
        const bDisagree = b.arkePosition === "DISAGREE" ? 1 : 0;
        if (aDisagree !== bDisagree) return bDisagree - aDisagree;
        return b.volume24hr - a.volume24hr;
    });

    return (
        <main className="bg-black min-h-screen">
            <StatsBar markets={markets} />
            <div className="px-4 py-4">
                <div className="text-xs font-mono text-neutral-600 mb-4">
                    // {new Date().toISOString().slice(0, 19)}Z — live prediction market intelligence
                    — markets where ARKE DISAGREES represent highest divergence from consensus
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                    {sorted.map(m => (
                        <MarketCard key={m.conditionId} m={m} />
                    ))}
                </div>
                {markets.length === 0 && (
                    <div className="text-neutral-600 text-sm font-mono text-center py-20">
                        FETCHING MARKET INTELLIGENCE...
                    </div>
                )}
            </div>
        </main>
    );
}
