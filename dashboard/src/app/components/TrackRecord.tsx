"use client";

import { useState } from "react";
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";
import type { TrackRecordCall, TrackRecordSummary } from "../api/intelligence/route";

const ARCSCAN = "https://testnet.arcscan.app";
const POLYGONSCAN = "https://polygonscan.com";
const ERC8004_REGISTRY = "0x8004A818BFB912233c491871b3d84c89A494BD9e";
const ERC8004_REP_REGISTRY = "0x8004B663056A597Dffe9eCcC1965A193B7388713";
const ORACLE_FALLBACK = "0x767D0eD2850D57C4EF969976088Be44A5Adcfa07";

function CopyButton({ value }: { value: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            type="button"
            onClick={() => {
                navigator.clipboard?.writeText(value).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1200);
                });
            }}
            className="text-neutral-500 hover:text-amber-400 border border-neutral-700 px-1"
        >
            {copied ? "copied" : "copy"}
        </button>
    );
}

function HashRow({
    label,
    value,
    href,
}: {
    label: string;
    value: string | null;
    href: string | null;
}) {
    if (!value) return null;
    return (
        <div className="flex items-center gap-2 text-xs font-mono py-0.5">
            <span className="text-neutral-500 w-32 shrink-0">{label}</span>
            {href ? (
                <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-500 hover:text-amber-300 truncate"
                >
                    {value.length > 24 ? `${value.slice(0, 24)}…` : value}
                </a>
            ) : (
                <span className="text-neutral-300 truncate">{value}</span>
            )}
            <CopyButton value={value} />
        </div>
    );
}

function rollingAccuracySeries(calls: TrackRecordCall[]) {
    // Resolved calls oldest-first; rolling accuracy after each resolution.
    const resolved = calls
        .filter((c) => c.resolved && c.postedAt)
        .sort((a, b) => (a.postedAt! < b.postedAt! ? -1 : 1));

    let correct = 0;
    return resolved.map((c, i) => {
        if (c.wasCorrect) correct += 1;
        return {
            date: (c.postedAt ?? "").slice(0, 10),
            accuracy: Math.round((correct / (i + 1)) * 100),
        };
    });
}

export function TrackRecord({
    summary,
    calls,
    oracleContract,
}: {
    summary: TrackRecordSummary | null;
    calls: TrackRecordCall[];
    oracleContract: string | null;
}) {
    const [openCid, setOpenCid] = useState<string | null>(null);
    const series = rollingAccuracySeries(calls);
    const recentCalls = [...calls]
        .sort((a, b) => ((a.postedAt ?? "") < (b.postedAt ?? "") ? 1 : -1))
        .slice(0, 20);

    return (
        <section className="border-b border-neutral-800 bg-neutral-950 px-4 py-5">
            {/* Header big numbers */}
            <div className="flex flex-wrap items-end gap-x-8 gap-y-2 font-mono">
                {summary ? (
                    <>
                        <Stat value={String(summary.nTotal)} label={`CALLS SINCE MAY 18 2026`} />
                        <Stat value={String(summary.nResolved)} label="RESOLVED" />
                        <Stat value={`${summary.directionalPct}%`} label="DIRECTIONAL" accent />
                        <Stat
                            value={`${summary.skillBps >= 0 ? "+" : ""}${summary.skillBps}`}
                            label="SKILL bps"
                        />
                        <Stat value={String(summary.brierIndex)} label="BRIER" />
                    </>
                ) : (
                    <span className="text-neutral-500 text-sm">Track record loading…</span>
                )}
                {oracleContract && (
                    <a
                        href={`${ARCSCAN}/address/${oracleContract}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-amber-500 hover:text-amber-300 ml-auto"
                    >
                        Verify on-chain →
                    </a>
                )}
                <a
                    href={`${ARCSCAN}/address/${ERC8004_REGISTRY}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`text-xs text-neutral-500 hover:text-neutral-300 ${oracleContract ? "" : "ml-auto"}`}
                >
                    ERC-8004 ID #20360
                </a>
                <a
                    href={`${ARCSCAN}/address/${ERC8004_REP_REGISTRY}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-neutral-500 hover:text-neutral-300"
                >
                    ERC-8004 Reputation →
                </a>
            </div>

            {/* What the numbers mean */}
            {summary && summary.nResolved > 0 && (
                <div className="text-xs text-neutral-600 font-mono mt-2">
                    {"// "}directional (binary correct) · skill vs random (Murphy 1973) ·
                    on-chain edge (beat consensus) — see{" "}
                    <a href="/calibration" className="text-amber-700 hover:text-amber-500">
                        /calibration
                    </a>
                    <a
                        href={`${ARCSCAN}/address/${oracleContract ?? ORACLE_FALLBACK}#readContract`}
                        className="text-amber-700 hover:text-amber-500 ml-2"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        verify →
                    </a>
                </div>
            )}

            {/* Accuracy trajectory */}
            <div className="mt-5">
                {series.length < 3 ? (
                    <div className="border border-neutral-800 p-3">
                        <div className="text-xs text-neutral-500 font-mono mb-3">
                            {"// "}accuracy trajectory — {summary?.nResolved ?? 0} resolved so far
                        </div>
                        {calls.filter((c) => c.resolved).map((c) => (
                            <div
                                key={c.conditionId}
                                className="flex justify-between text-xs font-mono py-1 border-b border-neutral-900"
                            >
                                <span className="text-neutral-300 truncate max-w-[60%]">
                                    {(c.question ?? "").slice(0, 55)}
                                </span>
                                <span className={c.wasCorrect ? "text-green-400" : "text-red-400"}>
                                    {c.wasCorrect ? "✓ CORRECT" : "✗ INCORRECT"}
                                </span>
                            </div>
                        ))}
                        <div className="text-xs text-neutral-600 font-mono mt-2">
                            chart renders at 3+ resolved markets
                        </div>
                    </div>
                ) : (
                    <div className="h-48">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                                <CartesianGrid stroke="#262626" strokeDasharray="3 3" />
                                <XAxis dataKey="date" stroke="#525252" fontSize={11} />
                                <YAxis domain={[0, 100]} stroke="#525252" fontSize={11} />
                                <Tooltip
                                    contentStyle={{ background: "#0a0a0a", border: "1px solid #404040", fontSize: 12 }}
                                    labelStyle={{ color: "#a3a3a3" }}
                                />
                                <Line
                                    type="monotone"
                                    dataKey="accuracy"
                                    stroke="#f59e0b"
                                    strokeWidth={2}
                                    dot={{ r: 2 }}
                                    isAnimationActive={false}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                )}
            </div>

            {/* Live calls table */}
            <div className="mt-5 overflow-x-auto">
                <table className="w-full text-xs font-mono">
                    <thead>
                        <tr className="text-neutral-500 text-left border-b border-neutral-800">
                            <th className="py-1 pr-2 font-normal">QUESTION</th>
                            <th className="py-1 px-2 font-normal text-right">ARKE</th>
                            <th className="py-1 px-2 font-normal text-right">MKT</th>
                            <th className="py-1 px-2 font-normal text-right">EDGE</th>
                            <th className="py-1 px-2 font-normal">POS</th>
                            <th className="py-1 px-2 font-normal">STATUS</th>
                            <th className="py-1 px-2 font-normal text-center">✓</th>
                            <th className="py-1 pl-2 font-normal" />
                        </tr>
                    </thead>
                    <tbody>
                        {recentCalls.map((c) => {
                            const edge = c.divergenceBps;
                            const pos =
                                edge === null ? "—"
                              : Math.abs(edge) <= 300 ? "AGREE"
                              : edge > 0 ? "BULL"
                              : "BEAR";
                            const status = !c.resolved ? "OPEN" : c.outcome ?? "—";
                            const correct =
                                c.wasCorrect === null ? "—" : c.wasCorrect ? "✓" : "✗";
                            const open = openCid === c.conditionId;
                            return (
                                <ConditionRows
                                    key={c.conditionId}
                                    call={c}
                                    edge={edge}
                                    pos={pos}
                                    status={status}
                                    correct={correct}
                                    open={open}
                                    onToggle={() =>
                                        setOpenCid(open ? null : c.conditionId)
                                    }
                                />
                            );
                        })}
                        {recentCalls.length === 0 && (
                            <tr>
                                <td colSpan={8} className="py-6 text-center text-neutral-600">
                                    No calls yet.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </section>
    );
}

function Stat({ value, label, accent }: { value: string; label: string; accent?: boolean }) {
    return (
        <div>
            <div className={`text-3xl font-bold tabular-nums ${accent ? "text-amber-400" : "text-neutral-100"}`}>
                {value}
            </div>
            <div className="text-xs text-neutral-500">{label}</div>
        </div>
    );
}

function ConditionRows({
    call,
    edge,
    pos,
    status,
    correct,
    open,
    onToggle,
}: {
    call: TrackRecordCall;
    edge: number | null;
    pos: string;
    status: string;
    correct: string;
    open: boolean;
    onToggle: () => void;
}) {
    const posColor =
        pos === "BEAR" || pos === "DISAGREE" ? "text-red-400"
      : pos === "BULL" ? "text-green-400"
      : "text-neutral-400";
    const correctColor =
        correct === "✓" ? "text-green-400" : correct === "✗" ? "text-red-400" : "text-neutral-600";

    return (
        <>
            <tr
                onClick={onToggle}
                className="border-b border-neutral-900 hover:bg-neutral-900 cursor-pointer"
            >
                <td className="py-1.5 pr-2 text-neutral-200">
                    {(call.question ?? "").slice(0, 60)}
                </td>
                <td className="py-1.5 px-2 text-right text-amber-400 tabular-nums">
                    {call.arkeProbability ?? "—"}%
                </td>
                <td className="py-1.5 px-2 text-right text-neutral-400 tabular-nums">
                    {call.marketProbability ?? "—"}%
                </td>
                <td className="py-1.5 px-2 text-right tabular-nums text-neutral-300">
                    {edge === null ? "—" : `${edge > 0 ? "+" : ""}${edge}bps`}
                </td>
                <td className={`py-1.5 px-2 ${posColor}`}>{pos}</td>
                <td className="py-1.5 px-2 text-neutral-300">{status}</td>
                <td className={`py-1.5 px-2 text-center ${correctColor}`}>{correct}</td>
                <td className="py-1.5 pl-2">
                    {call.oracleLogTx ? (
                        <span className="text-amber-500 text-xs border border-amber-800 px-1">
                            {open ? "hide" : "⛓ onchain"}
                        </span>
                    ) : (
                        <span className="text-neutral-600 text-xs">{open ? "▾" : "▸"}</span>
                    )}
                </td>
            </tr>
            {open && (
                <tr className="bg-neutral-950 border-b border-neutral-900">
                    <td colSpan={8} className="py-2 px-2">
                        <HashRow
                            label="stake tx"
                            value={call.stakeTx}
                            href={call.stakeTx ? `${POLYGONSCAN}/tx/${call.stakeTx}` : null}
                        />
                        <HashRow
                            label="oracle log tx"
                            value={call.oracleLogTx}
                            href={call.oracleLogTx ? `${ARCSCAN}/tx/${call.oracleLogTx}` : null}
                        />
                        <HashRow
                            label="oracle resolve tx"
                            value={call.oracleResolveTx}
                            href={call.oracleResolveTx ? `${ARCSCAN}/tx/${call.oracleResolveTx}` : null}
                        />
                        <HashRow
                            label="reasoning hash"
                            value={call.reasoningCid}
                            href={
                                call.conditionId
                                    ? `https://arke.live/traces/${call.conditionId.slice(0, 16)}.json`
                                    : null
                            }
                        />
                        <HashRow
                            label="x post"
                            value={call.xPostUrl}
                            href={call.xPostUrl}
                        />
                        {!call.stakeTx &&
                            !call.oracleLogTx &&
                            !call.oracleResolveTx &&
                            !call.reasoningCid &&
                            !call.xPostUrl && (
                                <div className="text-xs text-neutral-600 font-mono">
                                    No on-chain artifacts recorded for this call yet.
                                </div>
                            )}
                    </td>
                </tr>
            )}
        </>
    );
}
