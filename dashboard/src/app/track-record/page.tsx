import { TrackRecord } from "../components/TrackRecord";
import { siteBase } from "@/lib/site";
import type { TrackRecordCall, TrackRecordSummary } from "../api/intelligence/route";

export const revalidate = 60;

async function getData(): Promise<{
    trackRecord: TrackRecordSummary | null;
    calls: TrackRecordCall[];
    oracleContract: string | null;
}> {
    const host = siteBase();
    try {
        const r = await fetch(`${host}/api/intelligence`, { next: { revalidate: 60 } });
        if (!r.ok) return { trackRecord: null, calls: [], oracleContract: null };
        const d = await r.json();
        return {
            trackRecord: d.trackRecord ?? null,
            calls: d.calls ?? [],
            oracleContract: d.oracleContract ?? null,
        };
    } catch {
        return { trackRecord: null, calls: [], oracleContract: null };
    }
}

export default async function TrackRecordPage() {
    const { trackRecord, calls, oracleContract } = await getData();
    return (
        <main className="bg-black min-h-screen font-data">
            <div className="border-b border-neutral-800 px-4 py-2 flex gap-4 text-xs">
                <a href="/" className="text-amber-400 font-bold">ARKE</a>
                <span className="text-neutral-600">/</span>
                <span className="text-neutral-400">track record</span>
                <a href="/calibration" className="ml-auto text-neutral-500 hover:text-amber-400">
                    calibration →
                </a>
            </div>
            <TrackRecord summary={trackRecord} calls={calls} oracleContract={oracleContract} />
        </main>
    );
}
