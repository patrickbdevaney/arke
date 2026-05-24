import { LiveIndicator } from "./components/LiveIndicator";
import { TrackRecord } from "./components/TrackRecord";
import { siteBase } from "@/lib/site";
import type {
    MarketIntelligence,
    TrackRecordCall,
    TrackRecordSummary,
} from "./api/intelligence/route";

export const revalidate = 60;

type IntelligenceResponse = {
    markets: MarketIntelligence[];
    trackRecord: TrackRecordSummary | null;
    calls: TrackRecordCall[];
    oracleContract: string | null;
};

async function getData(): Promise<IntelligenceResponse> {
    const host = siteBase();
    const empty: IntelligenceResponse = {
        markets: [],
        trackRecord: null,
        calls: [],
        oracleContract: null,
    };
    try {
        const r = await fetch(`${host}/api/intelligence`, {
            next: { revalidate: 60 }
        });
        if (!r.ok) return empty;
        const data = await r.json();
        return {
            markets: data.markets ?? [],
            trackRecord: data.trackRecord ?? null,
            calls: data.calls ?? [],
            oracleContract: data.oracleContract ?? null,
        };
    } catch {
        return empty;
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
    const isBearish = position === "DISAGREE" || position === "BEAR";
    return (
        <span className={`text-xs px-1 border font-bold ${
            isBearish
                ? "text-red-400 border-red-800 bg-red-950"
                : "text-green-400 border-green-800 bg-green-950"
        }`}>
            ARKE {position}S
        </span>
    );
}

function daysLeftOf(endDateIso: string): number | null {
    if (!endDateIso) return null;
    return Math.max(0, Math.ceil(
        (new Date(endDateIso).getTime() - Date.now()) / 86_400_000
    ));
}

function MarketMeta({ m }: { m: MarketIntelligence }) {
    return (
        <div className="flex justify-between text-xs text-neutral-500 font-mono">
            <span>${(m.volume24hr / 1000).toFixed(0)}K/24h</span>
            <span>spread {(m.spread * 100).toFixed(1)}¢</span>
            <span>ends {m.endDateIso?.slice(0, 10) ?? "—"}</span>
        </div>
    );
}

function MarketCard({ m }: { m: MarketIntelligence }) {
    return m.arkeEstimatePct !== null
        ? <CoveredCard m={m} />
        : <MonitoringCard m={m} />;
}

// Mode A — Arke has published a take on this market.
function CoveredCard({ m }: { m: MarketIntelligence }) {
    const hasDivergence = m.divergencePts !== null;
    const divergenceColor = !hasDivergence ? ""
        : m.divergencePts! > 0 ? "text-green-400"
        : "text-red-400";
    const divergenceStr = !hasDivergence ? "—"
        : `${m.divergencePts! > 0 ? "+" : ""}${m.divergencePts}pts`;
    const daysLeft = daysLeftOf(m.endDateIso);

    return (
        <div className="flex flex-col border border-neutral-800 bg-neutral-950 p-3 hover:border-amber-600 transition-colors">
            {/* Clickable body → Polymarket */}
            <a
                href={`https://${m.betUrl}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block"
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
                            {m.arkeEstimatePct}%
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
                <div className="mb-2">
                    <MarketMeta m={m} />
                </div>
            </a>

            {/* Arke's analysis — the tweet text IS the product */}
            {m.councilForecast ? (
                <div className="border-t border-neutral-800 pt-2 mt-auto">
                    <blockquote className="text-xs text-neutral-300 border-l-2 border-amber-800 pl-2 font-mono leading-relaxed">
                        &ldquo;{m.councilForecast}&rdquo;
                    </blockquote>
                    {m.tweetUrl && (
                        <a
                            href={m.tweetUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-amber-600 hover:text-amber-400 mt-1.5 inline-block font-mono"
                        >
                            → View on @arke_ai
                        </a>
                    )}
                </div>
            ) : (
                m.tweetUrl && (
                    <a
                        href={m.tweetUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-amber-600 hover:text-amber-400 mt-auto pt-1 font-mono"
                    >
                        → @arke_ai analysis
                    </a>
                )
            )}
        </div>
    );
}

// Mode B — Arke is monitoring this market but has not published a take.
function MonitoringCard({ m }: { m: MarketIntelligence }) {
    const daysLeft = daysLeftOf(m.endDateIso);

    return (
        <a
            href={`https://${m.betUrl}`}
            target="_blank"
            rel="noopener noreferrer"
            className="block border border-neutral-800/60 bg-neutral-950 p-3 hover:border-neutral-600 transition-colors"
        >
            {/* Header: badges */}
            <div className="flex items-center gap-2 mb-2 flex-wrap">
                <LiquidityBadge score={m.liquidityScore} />
                <span className="text-xs text-neutral-500 border border-neutral-700 px-1">
                    MONITORING
                </span>
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

            {/* Market consensus only */}
            <div className="text-xs font-mono mb-2">
                <div className="text-neutral-500 mb-0.5">MARKET</div>
                <div className="text-green-400 text-xl font-bold tabular-nums">
                    {m.probabilityPct}%
                </div>
            </div>

            {/* Volume and spread */}
            <MarketMeta m={m} />
        </a>
    );
}

function StatsBar({ markets, trackRecord }: {
    markets: MarketIntelligence[];
    trackRecord: TrackRecordSummary | null;
}) {
    const disagrees = markets.filter(m =>
        m.arkePosition === "BEAR" || m.arkePosition === "DISAGREE");

    return (
        <header className="border-b border-neutral-800 bg-black sticky top-0 z-10">
            {/* Identity row */}
            <div className="px-4 py-1.5 flex items-center gap-x-4 text-xs font-mono border-b border-neutral-900">
                <span className="text-amber-400 font-bold tracking-widest text-sm">
                    ARKE
                </span>
                <span className="text-neutral-600">|</span>
                <span className="text-neutral-500 hidden sm:inline">
                    autonomous prediction market intelligence
                </span>
                <span className="text-neutral-600 hidden sm:inline">|</span>
                <a
                    href="https://x.com/arke_ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-500 hover:text-amber-300"
                >
                    @arke_ai
                </a>
                <span className="text-neutral-600">|</span>
                <a
                    href="https://testnet.arcscan.app/address/0x767D0eD2850D57C4EF969976088Be44A5Adcfa07"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-neutral-500 hover:text-amber-400"
                >
                    ⛓ oracle
                </a>
                <a
                    href="/oracle"
                    className="text-neutral-500 hover:text-amber-400 hidden sm:inline"
                >
                    verify →
                </a>
                <span className="ml-auto">
                    <LiveIndicator />
                </span>
            </div>
            {/* Stats row */}
            <div className="px-4 py-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs font-mono">
                {trackRecord ? (
                    <>
                        <span>
                            <span className="text-amber-400 tabular-nums">
                                {trackRecord.nTotal}
                            </span>
                            <span className="text-neutral-500"> CALLS</span>
                        </span>
                        <span className="text-neutral-700">|</span>
                        <span>
                            <span className="text-neutral-200 tabular-nums">
                                {trackRecord.nResolved}
                            </span>
                            <span className="text-neutral-500"> RESOLVED</span>
                        </span>
                        <span className="text-neutral-700">|</span>
                        <span>
                            <span className="text-green-400 tabular-nums">
                                {trackRecord.accuracyPct}%
                            </span>
                            <span className="text-neutral-500"> ACCURATE</span>
                        </span>
                        <span className="text-neutral-700">|</span>
                    </>
                ) : null}
                <span>
                    <span className="text-neutral-400 tabular-nums">
                        {markets.length}
                    </span>
                    <span className="text-neutral-500"> MONITORING</span>
                </span>
                <span className="text-neutral-700">|</span>
                <span>
                    <span className="text-red-400 tabular-nums">
                        {disagrees.length}
                    </span>
                    <span className="text-neutral-500"> ARKE DISAGREES</span>
                </span>
            </div>
        </header>
    );
}

export default async function Page() {
    const { markets, trackRecord, calls, oracleContract } = await getData();

    // Sort: Arke-analyzed and divergent calls first, then by volume
    const sorted = [...markets].sort((a, b) => {
        const aHas = a.arkeEstimatePct !== null ? 1 : 0;
        const bHas = b.arkeEstimatePct !== null ? 1 : 0;
        if (aHas !== bHas) return bHas - aHas;
        const aDiverge = a.arkePosition === "DISAGREE" || a.arkePosition === "BEAR" ? 1 : 0;
        const bDiverge = b.arkePosition === "DISAGREE" || b.arkePosition === "BEAR" ? 1 : 0;
        if (aDiverge !== bDiverge) return bDiverge - aDiverge;
        return b.volume24hr - a.volume24hr;
    });

    // Two-mode split: covered markets (Arke has a take) lead; monitored
    // markets (not yet covered) follow under a section label.
    const covered = sorted.filter(m => m.arkeEstimatePct !== null);
    const monitoring = sorted.filter(m => m.arkeEstimatePct === null);

    return (
        <main className="bg-black min-h-screen">
            <StatsBar markets={markets} trackRecord={trackRecord} />
            <TrackRecord
                summary={trackRecord}
                calls={calls}
                oracleContract={oracleContract}
            />
            <div className="px-4 py-4">
                <div className="text-xs font-mono text-neutral-600 mb-4">
                    // {new Date().toISOString().slice(0, 19)}Z — live prediction market intelligence
                    — markets where ARKE DISAGREES represent highest divergence from consensus
                </div>

                {covered.length > 0 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2 items-stretch">
                        {covered.map(m => (
                            <MarketCard key={m.conditionId} m={m} />
                        ))}
                    </div>
                )}

                {monitoring.length > 0 && (
                    <>
                        <div className="text-xs font-mono text-neutral-600 mt-6 mb-3">
                            // monitoring — {monitoring.length} markets not yet covered by Arke
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2 items-stretch">
                            {monitoring.map(m => (
                                <MarketCard key={m.conditionId} m={m} />
                            ))}
                        </div>
                    </>
                )}

                {markets.length === 0 && (
                    <div className="text-neutral-600 text-sm font-mono text-center py-20">
                        FETCHING MARKET INTELLIGENCE...
                    </div>
                )}
            </div>

            <footer className="border-t border-neutral-800 mt-8 px-4 py-6 text-xs font-mono text-neutral-600">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                    <div>
                        <div className="text-neutral-400 mb-2">WHAT ARKE IS</div>
                        <p className="leading-relaxed">
                            An autonomous AI agent that monitors Polymarket every 6 hours,
                            generates calibrated probability estimates using a multi-agent
                            council, and logs every prediction to an immutable onchain oracle
                            on Arc testnet. Operating since May 18 2026 with zero human
                            intervention.
                        </p>
                    </div>
                    <div>
                        <div className="text-neutral-400 mb-2">THE MOAT</div>
                        <p className="leading-relaxed">
                            A permanently growing correctness ledger: every prediction is
                            signed, staked, and resolved onchain. The track record compounds
                            daily and cannot be retroactively manufactured. ICE distributes
                            what the crowd thinks; Arke documents whether the crowd was wrong.
                        </p>
                    </div>
                    <div>
                        <div className="text-neutral-400 mb-2">REVENUE</div>
                        <p className="leading-relaxed">
                            Polymarket V2 builder fees flow automatically on every trade
                            originating from Arke&apos;s links. Intelligence feed available via
                            x402 micropayments at feed.arke.live:8402. Institutional
                            subscription tier in development.
                        </p>
                    </div>
                </div>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-neutral-700 border-t border-neutral-900 pt-4">
                    <a href="/oracle" className="hover:text-amber-500">Oracle →</a>
                    <a href="https://x.com/arke_ai" target="_blank" rel="noopener noreferrer"
                       className="hover:text-amber-500">@arke_ai →</a>
                    <a href="https://testnet.arcscan.app/address/0x767D0eD2850D57C4EF969976088Be44A5Adcfa07"
                       target="_blank" rel="noopener noreferrer" className="hover:text-amber-500">
                        Arc Contract →
                    </a>
                    <a href="http://feed.arke.live:8402/healthz"
                       target="_blank" rel="noopener noreferrer" className="hover:text-amber-500">
                        Feed API →
                    </a>
                    <span className="ml-auto">
                        ERC-8004 Agent #20360 · built on Arc × Circle × Polymarket
                    </span>
                </div>
            </footer>
        </main>
    );
}
