"use client";

import { useEffect, useRef, useState } from "react";
import type {
    MarketIntelligence,
    TrackRecordCall,
} from "../api/intelligence/route";
import { TradeWidget } from "./TradeWidget";

const ARCSCAN = "https://testnet.arcscan.app";

type Tab = "covered" | "monitoring" | "resolved";

// ── shared helpers ────────────────────────────────────────────────────

function daysLeftOf(endDateIso: string): number | null {
    if (!endDateIso) return null;
    return Math.max(0, Math.ceil(
        (new Date(endDateIso).getTime() - Date.now()) / 86_400_000
    ));
}

// Per-call Murphy (1973) skill score vs a flat-50% reference, in bps.
// Mirrors agent/db.get_dual_scores + resolver._per_call_skill_bps.
function perCallSkillBps(arkePct: number, outcomeYes: boolean): number {
    const p = Math.max(0.01, Math.min(0.99, arkePct / 100));
    const y = outcomeYes ? 1 : 0;
    const brier = (p - y) ** 2;
    const ref = (0.5 - y) ** 2; // 0.25
    return Math.round((1 - brier / ref) * 10000);
}

function LiquidityBadge({ score }: { score: string }) {
    const colors: Record<string, string> = {
        deep: "text-green-400 border-green-800",
        moderate: "text-amber-400 border-amber-800",
        thin: "text-neutral-400 border-neutral-700",
    };
    return (
        <span className={`text-xs border px-1 font-data ${colors[score] ?? colors.thin}`}>
            {score.toUpperCase()}
        </span>
    );
}

// BEAR/DISAGREE is blue (a contrarian stance, not a loss). Green for BULL/AGREE.
// Red is reserved for resolution losses + errors only.
function PositionBadge({ position }: { position: string | null }) {
    if (!position || position === "NEUTRAL") return null;
    const isBearish = position === "DISAGREE" || position === "BEAR";
    return (
        <span className={`text-xs px-1 border font-bold font-data ${
            isBearish
                ? "text-blue-400 border-blue-800 bg-blue-950"
                : "text-green-400 border-green-800 bg-green-950"
        }`}>
            ARKE {position}S
        </span>
    );
}

// Lazy-mount below-fold content: renders a placeholder until it scrolls near
// the viewport, then swaps in the real child once.
function LazyItem({ children }: { children: React.ReactNode }) {
    const ref = useRef<HTMLDivElement>(null);
    const [shown, setShown] = useState(false);
    useEffect(() => {
        const el = ref.current;
        if (!el || shown) return;
        const obs = new IntersectionObserver(
            (entries) => {
                if (entries.some((e) => e.isIntersecting)) {
                    setShown(true);
                    obs.disconnect();
                }
            },
            { rootMargin: "300px" }
        );
        obs.observe(el);
        return () => obs.disconnect();
    }, [shown]);
    return (
        <div ref={ref} className="w-full max-w-[360px]">
            {shown ? children : <div className="h-64 border border-[#1a1a1a] bg-[#0f0f0f]" />}
        </div>
    );
}

// ── COVERED card ──────────────────────────────────────────────────────

function CoveredCard({ m }: { m: MarketIntelligence }) {
    const hasDivergence = m.divergencePts !== null;
    const divergenceColor = !hasDivergence ? "text-neutral-400"
        : m.divergencePts! > 0 ? "text-green-400"
        : "text-blue-400";
    const divergenceStr = !hasDivergence ? "—"
        : `${m.divergencePts! > 0 ? "+" : ""}${m.divergencePts} pts`;
    const daysLeft = daysLeftOf(m.endDateIso);

    return (
        <div className="flex flex-col w-full max-w-[360px] border border-[#2a2a2a] bg-[#141414] p-3 hover:border-amber-600 transition-colors">
            {/* One inline badge row: liquidity + position + (≤7d) deadline */}
            <div className="flex items-center gap-2 mb-2 flex-wrap">
                <LiquidityBadge score={m.liquidityScore} />
                <PositionBadge position={m.arkePosition} />
                {daysLeft !== null && daysLeft <= 7 && (
                    <span className="text-xs text-amber-400 border border-amber-800 px-1 font-data">
                        {daysLeft}D LEFT
                    </span>
                )}
            </div>

            {/* Question (prose) */}
            <a
                href={`https://${m.betUrl}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block text-sm text-neutral-100 leading-snug mb-3 font-prose hover:text-amber-300 transition-colors"
            >
                {m.question}
            </a>

            {/* Core numbers — desktop 3-col grid */}
            <div className="hidden sm:grid grid-cols-3 gap-2 font-data mb-2">
                <Metric label="MARKET" value={`${m.probabilityPct}%`} cls="text-green-400" />
                <Metric label="ARKE" value={`${m.arkeEstimatePct}%`} cls="text-amber-400" />
                <Metric label="EDGE" value={divergenceStr} cls={divergenceColor} />
            </div>

            {/* Core numbers — mobile stacked: MARKET, then ARKE with EDGE pill */}
            <div className="sm:hidden font-data mb-2 space-y-1">
                <Metric label="MARKET" value={`${m.probabilityPct}%`} cls="text-green-400" />
                <div className="flex items-end gap-2">
                    <Metric label="ARKE" value={`${m.arkeEstimatePct}%`} cls="text-amber-400" />
                    {hasDivergence && (
                        <span className={`mb-1 text-xs border px-1.5 py-0.5 tabular-nums ${
                            m.divergencePts! > 0
                                ? "text-green-400 border-green-800"
                                : "text-blue-400 border-blue-800"
                        }`}>
                            {divergenceStr}
                        </span>
                    )}
                </div>
            </div>

            {/* Demoted secondary data */}
            <div className="flex justify-between text-xs text-neutral-500 font-data mb-2">
                <span>${(m.volume24hr / 1000).toFixed(0)}K/24h</span>
                <span>spread {(m.spread * 100).toFixed(1)}¢</span>
                {m.endDateIso && <span>ends {m.endDateIso.slice(0, 10)}</span>}
            </div>

            {/* Council reasoning — disclosure, default closed */}
            {m.councilForecast && (
                <details className="border-t border-neutral-800 pt-2 mt-auto group">
                    <summary className="text-xs text-amber-600 hover:text-amber-400 font-data cursor-pointer list-none">
                        ▾ council reasoning
                    </summary>
                    <blockquote className="mt-2 text-xs text-neutral-300 border-l-2 border-amber-800 pl-2 font-prose leading-relaxed">
                        &ldquo;{m.councilForecast}&rdquo;
                    </blockquote>
                    {m.tweetUrl && (
                        <a
                            href={m.tweetUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-amber-600 hover:text-amber-400 mt-1.5 inline-block font-data"
                        >
                            → View on @arke_ai
                        </a>
                    )}
                </details>
            )}

            {/* Trade widget (wallet signing) → falls back to a plain link */}
            {m.yesTokenId ? (
                <TradeWidget
                    tokenId={m.yesTokenId}
                    question={m.question}
                    marketPct={m.probabilityPct}
                    arkeEstimate={m.arkeEstimatePct ?? m.probabilityPct}
                    betUrl={m.betUrl}
                />
            ) : (
                <a href={`https://${m.betUrl}`} target="_blank" rel="noopener noreferrer"
                   className="text-xs text-amber-600 hover:text-amber-400 font-data mt-2">
                    Trade on Polymarket ▸
                </a>
            )}
        </div>
    );
}

function Metric({ label, value, cls }: { label: string; value: string; cls: string }) {
    return (
        <div>
            <div className="text-neutral-500 text-xs mb-0.5">{label}</div>
            <div className={`text-3xl font-bold tabular-nums ${cls}`}>{value}</div>
        </div>
    );
}

// ── MONITORING row ────────────────────────────────────────────────────

function MonitoringRow({ m }: { m: MarketIntelligence }) {
    const end = m.endDateIso ? m.endDateIso.slice(0, 10) : "—";
    return (
        <tr className="border-b border-neutral-900 hover:bg-neutral-900/60">
            <td className="py-1.5 pr-3 text-neutral-200 font-prose sticky left-0 bg-[#0a0a0a] z-10 max-w-[60vw] sm:max-w-none truncate">
                <a href={`https://${m.betUrl}`} target="_blank" rel="noopener noreferrer"
                   className="hover:text-amber-300">
                    {(m.question ?? "").slice(0, 60)}
                </a>
            </td>
            <td className="py-1.5 px-3 text-right text-green-400 tabular-nums">{m.probabilityPct}%</td>
            <td className="py-1.5 px-3 text-right text-neutral-400 tabular-nums">${(m.volume24hr / 1000).toFixed(0)}K</td>
            <td className="py-1.5 px-3 text-right text-neutral-400 tabular-nums">{(m.spread * 100).toFixed(1)}¢</td>
            <td className="py-1.5 pl-3 text-right text-neutral-500 tabular-nums">{end}</td>
        </tr>
    );
}

// ── RESOLVED row ──────────────────────────────────────────────────────

function ResolvedRow({ c }: { c: TrackRecordCall }) {
    const outcome = c.outcome ?? "—";
    const correct = c.wasCorrect;
    const skill = (c.arkeProbability !== null && c.outcome)
        ? perCallSkillBps(c.arkeProbability, c.outcome === "YES")
        : null;
    const logTx = c.oracleResolveTx ?? c.oracleLogTx;
    return (
        <tr className="border-b border-neutral-900 hover:bg-neutral-900/60">
            <td className="py-1.5 pr-3 text-neutral-200 font-prose sticky left-0 bg-[#0a0a0a] z-10 max-w-[60vw] sm:max-w-none truncate">
                {(c.question ?? "").slice(0, 60)}
            </td>
            <td className="py-1.5 px-3 text-right text-amber-400 tabular-nums">{c.arkeProbability ?? "—"}%</td>
            <td className="py-1.5 px-3 text-right text-neutral-400 tabular-nums">{c.marketProbability ?? "—"}%</td>
            <td className="py-1.5 px-3 text-center text-neutral-300">{outcome}</td>
            <td className={`py-1.5 px-3 text-center ${
                correct === null ? "text-neutral-600" : correct ? "text-green-400" : "text-red-400"
            }`}>
                {correct === null ? "—" : correct ? "✓" : "✗"}
            </td>
            <td className={`py-1.5 px-3 text-right tabular-nums ${
                skill === null ? "text-neutral-600" : skill >= 0 ? "text-green-400" : "text-red-400"
            }`}>
                {skill === null ? "—" : `${skill >= 0 ? "+" : ""}${skill}`}
            </td>
            <td className="py-1.5 pl-3 text-right">
                {logTx ? (
                    <a href={`${ARCSCAN}/tx/${logTx}`} target="_blank" rel="noopener noreferrer"
                       className="text-amber-600 hover:text-amber-400">⛓</a>
                ) : <span className="text-neutral-700">—</span>}
            </td>
        </tr>
    );
}

// ── Tab control + panels ──────────────────────────────────────────────

export function MarketTabs({
    covered,
    monitoring,
    resolved,
}: {
    covered: MarketIntelligence[];
    monitoring: MarketIntelligence[];
    resolved: TrackRecordCall[];
}) {
    const [tab, setTab] = useState<Tab>("covered");

    // Deep-link support without useSearchParams (keeps the ISR page out of the
    // Suspense-boundary requirement): read ?tab= on mount, write on change.
    useEffect(() => {
        const t = new URLSearchParams(window.location.search).get("tab");
        if (t === "covered" || t === "monitoring" || t === "resolved") setTab(t);
    }, []);

    function selectTab(t: Tab) {
        setTab(t);
        try {
            const url = new URL(window.location.href);
            url.searchParams.set("tab", t);
            window.history.replaceState(null, "", url.toString());
        } catch {
            /* non-browser / blocked — tab still switches in memory */
        }
    }

    const tabs: Array<{ id: Tab; label: string; n: number }> = [
        { id: "covered", label: "COVERED", n: covered.length },
        { id: "monitoring", label: "MONITORING", n: monitoring.length },
        { id: "resolved", label: "RESOLVED", n: resolved.length },
    ];

    return (
        <div>
            {/* Segmented control — full width on mobile */}
            <div className="flex w-full sm:w-auto border border-neutral-800 mb-4 font-data text-xs">
                {tabs.map((t) => (
                    <button
                        key={t.id}
                        onClick={() => selectTab(t.id)}
                        className={`flex-1 sm:flex-none px-4 py-2 transition-colors border-r border-neutral-800 last:border-r-0 ${
                            tab === t.id
                                ? "bg-amber-950 text-amber-300"
                                : "text-neutral-500 hover:text-neutral-300"
                        }`}
                    >
                        {t.label} <span className="tabular-nums">({t.n})</span>
                    </button>
                ))}
            </div>

            {tab === "covered" && (
                covered.length > 0 ? (
                    <div className="grid gap-3 justify-items-center sm:justify-items-start grid-cols-1 sm:grid-cols-2 min-[1440px]:grid-cols-3 min-[1920px]:grid-cols-4">
                        {covered.map((m, i) =>
                            i < 6 ? (
                                <CoveredCard key={m.conditionId} m={m} />
                            ) : (
                                <LazyItem key={m.conditionId}>
                                    <CoveredCard m={m} />
                                </LazyItem>
                            )
                        )}
                    </div>
                ) : (
                    <Empty text="No covered markets this cycle — see MONITORING." />
                )
            )}

            {tab === "monitoring" && (
                monitoring.length > 0 ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs font-data border-collapse">
                            <thead>
                                <tr className="text-neutral-500 text-left border-b border-neutral-800">
                                    <th className="py-1.5 pr-3 font-normal sticky left-0 bg-[#0a0a0a] z-10">QUESTION</th>
                                    <th className="py-1.5 px-3 font-normal text-right">MKT</th>
                                    <th className="py-1.5 px-3 font-normal text-right">VOL</th>
                                    <th className="py-1.5 px-3 font-normal text-right">SPREAD</th>
                                    <th className="py-1.5 pl-3 font-normal text-right">ENDS</th>
                                </tr>
                            </thead>
                            <tbody>
                                {monitoring.map((m) => (
                                    <MonitoringRow key={m.conditionId} m={m} />
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <Empty text="Nothing in the monitoring queue right now." />
                )
            )}

            {tab === "resolved" && (
                resolved.length > 0 ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs font-data border-collapse">
                            <thead>
                                <tr className="text-neutral-500 text-left border-b border-neutral-800">
                                    <th className="py-1.5 pr-3 font-normal sticky left-0 bg-[#0a0a0a] z-10">QUESTION</th>
                                    <th className="py-1.5 px-3 font-normal text-right">ARKE</th>
                                    <th className="py-1.5 px-3 font-normal text-right">MKT</th>
                                    <th className="py-1.5 px-3 font-normal text-center">OUTCOME</th>
                                    <th className="py-1.5 px-3 font-normal text-center">DIR</th>
                                    <th className="py-1.5 px-3 font-normal text-right">SKILL bps</th>
                                    <th className="py-1.5 pl-3 font-normal text-right">⛓</th>
                                </tr>
                            </thead>
                            <tbody>
                                {resolved.map((c) => (
                                    <ResolvedRow key={c.conditionId} c={c} />
                                ))}
                            </tbody>
                        </table>
                        <div className="text-xs text-neutral-600 font-data mt-3">
                            {"// "}DIR = directional (binary call correct) · SKILL = Murphy
                            (1973) skill vs a flat-50% reference, per call
                        </div>
                    </div>
                ) : (
                    <Empty text="No resolved calls yet — they appear here once markets settle." />
                )
            )}
        </div>
    );
}

function Empty({ text }: { text: string }) {
    return (
        <div className="text-neutral-600 text-sm font-data text-center py-16">{text}</div>
    );
}
