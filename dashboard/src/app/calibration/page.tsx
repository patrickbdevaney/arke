import { ReliabilityChart, type ReliabilityBin } from "../components/ReliabilityChart";

export const revalidate = 60;

const ORACLE = "0x767D0eD2850D57C4EF969976088Be44A5Adcfa07";

type Scores = {
    directional_pct: number;
    skill_bps: number;
    brier: number | null;
    n_resolved: number;
};

type CalibrationResponse = {
    scores: Scores;
    reliability_bins: ReliabilityBin[];
    operating_since: string;
    note: string;
};

async function getCalibration(): Promise<CalibrationResponse | null> {
    const base = process.env.ARKE_FEED_URL;
    if (!base) return null;
    try {
        // /v1/arke/calibration is always free (ungated) — no payment headers.
        const r = await fetch(`${base.replace(/\/$/, "")}/v1/arke/calibration`, {
            next: { revalidate: 60 },
        });
        if (!r.ok) return null;
        return (await r.json()) as CalibrationResponse;
    } catch {
        return null;
    }
}

export default async function CalibrationPage() {
    const data = await getCalibration();

    return (
        <main className="bg-black min-h-screen font-data">
            <div className="border-b border-neutral-800 px-4 py-2 flex gap-4 text-xs">
                <a href="/" className="text-amber-400 font-bold">ARKE</a>
                <span className="text-neutral-600">/</span>
                <span className="text-neutral-400">calibration</span>
                <a href="/oracle" className="ml-auto text-neutral-500 hover:text-amber-400">
                    oracle →
                </a>
            </div>

            <div className="px-4 py-6 max-w-3xl mx-auto">
                <div className="text-xs text-neutral-500 mb-1">
                    {"// "}reliability diagram — always free
                </div>
                <h1 className="text-2xl text-amber-400 font-bold mb-4">Calibration</h1>

                {!data ? (
                    <div className="text-neutral-600 text-sm py-16 text-center">
                        Calibration data unavailable.
                    </div>
                ) : (
                    <>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                            <Stat value={`${data.scores.directional_pct}%`} label="DIRECTIONAL" cls="text-green-400" />
                            <Stat
                                value={`${data.scores.skill_bps >= 0 ? "+" : ""}${data.scores.skill_bps}`}
                                label="SKILL bps"
                                cls={data.scores.skill_bps >= 0 ? "text-green-400" : "text-red-400"}
                            />
                            <Stat value={data.scores.brier === null ? "—" : String(data.scores.brier)} label="BRIER" />
                            <Stat value={String(data.scores.n_resolved)} label="RESOLVED" />
                        </div>

                        <div className="border border-neutral-800 p-4 mb-6">
                            <div className="text-xs text-neutral-500 mb-3">
                                {"// "}amber bars = empirical YES rate per forecast bin ·
                                blue dashed = perfect calibration
                            </div>
                            <ReliabilityChart bins={data.reliability_bins} />
                        </div>

                        <div className="text-xs text-neutral-500 font-prose leading-relaxed border-l-2 border-amber-800 pl-3">
                            {data.note}
                        </div>

                        <div className="text-xs text-neutral-600 font-data mt-4">
                            {"// "}directional (binary correct) · skill vs random (Murphy 1973)
                            · on-chain edge (beat consensus)
                            <a
                                href={`https://testnet.arcscan.app/address/${ORACLE}#readContract`}
                                className="text-amber-700 hover:text-amber-500 ml-2"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                verify →
                            </a>
                        </div>
                    </>
                )}
            </div>
        </main>
    );
}

function Stat({ value, label, cls }: { value: string; label: string; cls?: string }) {
    return (
        <div>
            <div className={`text-2xl font-bold tabular-nums ${cls ?? "text-neutral-100"}`}>
                {value}
            </div>
            <div className="text-xs text-neutral-500">{label}</div>
        </div>
    );
}
