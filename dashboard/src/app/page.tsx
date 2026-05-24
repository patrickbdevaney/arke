import { LiveIndicator } from "./components/LiveIndicator";
import { MarketTabs } from "./components/MarketTabs";
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

function StatCell({ value, label, cls }: { value: string; label: string; cls?: string }) {
    return (
        <span className="whitespace-nowrap shrink-0">
            <span className={`tabular-nums ${cls ?? "text-neutral-200"}`}>{value}</span>
            <span className="text-neutral-500"> {label}</span>
        </span>
    );
}

function StatsBar({ markets, trackRecord }: {
    markets: MarketIntelligence[];
    trackRecord: TrackRecordSummary | null;
}) {
    const disagrees = markets.filter(m =>
        m.arkePosition === "BEAR" || m.arkePosition === "DISAGREE");
    const skill = trackRecord?.skillBps ?? 0;

    return (
        <header className="border-b border-neutral-800 bg-black sticky top-0 z-20">
            {/* Identity row */}
            <div className="px-4 py-1.5 flex items-center gap-x-4 text-xs font-data border-b border-neutral-900">
                <span className="text-amber-400 font-bold tracking-widest text-sm">
                    ARKE
                </span>
                <span className="text-neutral-600">|</span>
                <span className="text-neutral-500 hidden sm:inline font-prose">
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
                <a
                    href="/oracle"
                    className="border border-amber-800 text-amber-400 hover:bg-amber-950 px-2 py-0.5 transition-colors"
                >
                    VERIFY ONCHAIN ↗
                </a>
                <a
                    href="/calibration"
                    className="text-neutral-500 hover:text-amber-400 hidden sm:inline"
                >
                    calibration →
                </a>
                <span className="ml-auto">
                    <LiveIndicator />
                </span>
            </div>
            {/* Stats row — scrollable chips on mobile, grid on sm+ */}
            <div className="px-4 py-2 flex gap-x-5 overflow-x-auto text-xs font-data sm:grid sm:grid-cols-3 lg:grid-cols-5 sm:gap-x-4 sm:gap-y-1 sm:overflow-visible">
                {trackRecord ? (
                    <>
                        <StatCell value={String(trackRecord.nTotal)} label="CALLS" cls="text-amber-400" />
                        <StatCell value={String(trackRecord.nResolved)} label="RESOLVED" />
                        <StatCell value={`${trackRecord.directionalPct}%`} label="DIRECTIONAL" cls="text-green-400" />
                        <StatCell
                            value={`${skill >= 0 ? "+" : ""}${skill}`}
                            label="SKILL bps"
                            cls={skill >= 0 ? "text-green-400" : "text-red-400"}
                        />
                    </>
                ) : null}
                <StatCell value={String(disagrees.length)} label="ARKE DISAGREES" cls="text-blue-400" />
            </div>
        </header>
    );
}

function TrackRecordSummaryStrip({
    trackRecord,
}: { trackRecord: TrackRecordSummary | null }) {
    if (!trackRecord) return null;
    const skill = trackRecord.skillBps;
    return (
        <div className="px-4 py-3 border-b border-neutral-900 text-xs font-data text-neutral-400 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="tabular-nums text-neutral-200">{trackRecord.nTotal}</span> calls
            <span className="text-neutral-700">·</span>
            <span className="tabular-nums text-neutral-200">{trackRecord.nResolved}</span> resolved
            <span className="text-neutral-700">·</span>
            directional <span className="tabular-nums text-green-400">{trackRecord.directionalPct}%</span>
            <span className="text-neutral-700">·</span>
            skill <span className={`tabular-nums ${skill >= 0 ? "text-green-400" : "text-red-400"}`}>
                {skill >= 0 ? "+" : ""}{skill} bps
            </span>
            <a href="/track-record" className="text-amber-600 hover:text-amber-400 ml-1">
                [full track record →]
            </a>
        </div>
    );
}

export default async function Page() {
    const { markets, trackRecord, calls } = await getData();

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

    const covered = sorted.filter(m => m.arkeEstimatePct !== null);
    const monitoring = sorted.filter(m => m.arkeEstimatePct === null);
    const resolved = [...calls]
        .filter(c => c.resolved)
        .sort((a, b) => ((a.postedAt ?? "") < (b.postedAt ?? "") ? 1 : -1));

    return (
        <main className="bg-black min-h-screen">
            <StatsBar markets={markets} trackRecord={trackRecord} />
            <TrackRecordSummaryStrip trackRecord={trackRecord} />

            <div className="px-4 py-4">
                <div className="text-xs font-data text-neutral-600 mb-4">
                    // {new Date().toISOString().slice(0, 19)}Z — live prediction market
                    intelligence — markets where ARKE DISAGREES represent highest divergence
                    from consensus
                </div>

                {markets.length === 0 && resolved.length === 0 ? (
                    <div className="text-neutral-600 text-sm font-data text-center py-20">
                        FETCHING MARKET INTELLIGENCE...
                    </div>
                ) : (
                    <MarketTabs
                        covered={covered}
                        monitoring={monitoring}
                        resolved={resolved}
                    />
                )}
            </div>

            <footer className="border-t border-neutral-800 mt-8 px-4 py-6 text-xs font-data text-neutral-600">
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-neutral-700">
                    <a href="/oracle" className="hover:text-amber-500">Oracle →</a>
                    <a href="/track-record" className="hover:text-amber-500">Track record →</a>
                    <a href="/calibration" className="hover:text-amber-500">Calibration →</a>
                    <a href="/about" className="hover:text-amber-500">About →</a>
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
                    <a href="https://testnet.arcscan.app/address/0x8004A818BFB912233c491871b3d84c89A494BD9e"
                       target="_blank" rel="noopener noreferrer" className="hover:text-amber-500">
                        ERC-8004 #20360 →
                    </a>
                    <span className="ml-auto font-prose">
                        Builder fees accrue only on trades placed through Arke&apos;s widget —
                        no funds at risk · built on Arc × Circle × Polymarket
                    </span>
                </div>
            </footer>
        </main>
    );
}
