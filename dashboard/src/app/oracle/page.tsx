import { siteBase } from "@/lib/site";
import type { TrackRecordCall } from "../api/intelligence/route";

export const revalidate = 60;

const ARCSCAN = "https://testnet.arcscan.app";
const ORACLE = "0x767D0eD2850D57C4EF969976088Be44A5Adcfa07";
const ERC8004_ID = "20360";
const ERC8004_REGISTRY = "0x8004A818BFB912233c491871b3d84c89A494BD9e";

async function getCalls(): Promise<{
  calls: TrackRecordCall[];
  oracleContract: string | null;
}> {
  try {
    // Use the public custom domain — the per-deployment VERCEL_URL is gated
    // by Vercel Deployment Protection (401) and would yield an empty page.
    const host = siteBase();
    const r = await fetch(`${host}/api/intelligence`,
                          { next: { revalidate: 60 } });
    if (!r.ok) return { calls: [], oracleContract: null };
    const d = await r.json();
    return { calls: d.calls ?? [], oracleContract: d.oracleContract ?? ORACLE };
  } catch {
    return { calls: [], oracleContract: ORACLE };
  }
}

export default async function OraclePage() {
  const { calls } = await getCalls();
  const resolved = calls.filter(c => c.resolved);
  const open = calls.filter(c => !c.resolved);

  return (
    <main className="bg-black min-h-screen font-mono">
      {/* Nav */}
      <div className="border-b border-neutral-800 px-4 py-2 flex gap-4 text-xs">
        <a href="/" className="text-amber-400 font-bold">ARKE</a>
        <span className="text-neutral-600">/</span>
        <span className="text-neutral-400">oracle verification</span>
      </div>

      <div className="px-4 py-6 max-w-4xl mx-auto">
        {/* Hero */}
        <div className="border border-neutral-800 p-6 mb-8">
          <div className="text-xs text-neutral-500 mb-1">
            {"// "}immutable prediction ledger
          </div>
          <h1 className="text-2xl text-amber-400 font-bold mb-4">
            PredictionMarketOracle.sol
          </h1>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            {[
              { label: "PREDICTIONS", value: String(calls.length) },
              { label: "RESOLVED", value: String(resolved.length) },
              { label: "CHAIN", value: "Arc Testnet" },
              { label: "ERC-8004 ID", value: `#${ERC8004_ID}` },
            ].map(({ label, value }) => (
              <div key={label}>
                <div className="text-2xl text-neutral-100 font-bold">
                  {value}
                </div>
                <div className="text-xs text-neutral-500">{label}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 text-xs">
            <a
              href={`${ARCSCAN}/address/${ORACLE}`}
              target="_blank" rel="noopener noreferrer"
              className="border border-amber-800 text-amber-500
                         hover:text-amber-300 px-3 py-1.5"
            >
              View contract on Arc Explorer →
            </a>
            <a
              href={`${ARCSCAN}/address/${ERC8004_REGISTRY}`}
              target="_blank" rel="noopener noreferrer"
              className="border border-neutral-700 text-neutral-400
                         hover:text-neutral-200 px-3 py-1.5"
            >
              ERC-8004 Identity #{ERC8004_ID} →
            </a>
          </div>
        </div>

        {/* How to verify */}
        <div className="border border-neutral-800 p-4 mb-8 text-xs">
          <div className="text-amber-400 mb-2">{"// "}verify it yourself</div>
          <div className="text-neutral-400 space-y-1">
            <p>1. Open the contract on Arc explorer (link above)</p>
            <p>2. Call <span className="text-amber-300">getPredictionCount()</span>
               {" "}— should return {calls.length}</p>
            <p>3. Call <span className="text-amber-300">getAccuracy()</span>
               {" "}— edge-vs-market metric (requires Arke to beat consensus)</p>
            <p>4. Each tx hash below links to the individual prediction record</p>
            <p>5. Resolution txs contain the outcome and correctness score</p>
          </div>
          <div className="mt-3 text-neutral-600">
            {"// "}contract address:{" "}
            <span className="text-neutral-400 select-all">{ORACLE}</span>
          </div>
        </div>

        {/* Resolved predictions */}
        {resolved.length > 0 && (
          <div className="mb-8">
            <div className="text-xs text-neutral-500 mb-3">
              {"// "}resolved predictions — {resolved.length} of {calls.length}
            </div>
            <div className="space-y-2">
              {resolved.map(c => (
                <OracleCallRow key={c.conditionId} call={c} />
              ))}
            </div>
          </div>
        )}

        {/* Open predictions */}
        <div>
          <div className="text-xs text-neutral-500 mb-3">
            {"// "}open predictions — awaiting resolution
          </div>
          <div className="space-y-2">
            {open.map(c => (
              <OracleCallRow key={c.conditionId} call={c} />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

function OracleCallRow({ call }: { call: TrackRecordCall }) {
  const correctColor = call.wasCorrect === true ? "text-green-400"
    : call.wasCorrect === false ? "text-red-400"
    : "text-neutral-600";

  return (
    <div className="border border-neutral-800 p-3 text-xs font-mono">
      <div className="flex items-start justify-between gap-4 mb-2">
        <span className="text-neutral-200">
          {(call.question ?? "").slice(0, 80)}
        </span>
        <span className={`shrink-0 ${correctColor}`}>
          {call.resolved
            ? (call.wasCorrect ? "✓ CORRECT" : "✗ INCORRECT")
            : "OPEN"}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-neutral-500">
        {call.arkeProbability !== null && (
          <span>
            arke <span className="text-amber-400">{call.arkeProbability}%</span>
            {" "}vs mkt{" "}
            <span className="text-neutral-300">{call.marketProbability}%</span>
          </span>
        )}
        {call.postedAt && (
          <span>{call.postedAt.slice(0, 10)}</span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-3">
        {call.oracleLogTx && (
          <a
            href={`${ARCSCAN}/tx/${call.oracleLogTx}`}
            target="_blank" rel="noopener noreferrer"
            className="text-amber-600 hover:text-amber-400"
          >
            log tx: {call.oracleLogTx.slice(0, 18)}… →
          </a>
        )}
        {call.oracleResolveTx && (
          <a
            href={`${ARCSCAN}/tx/${call.oracleResolveTx}`}
            target="_blank" rel="noopener noreferrer"
            className="text-green-600 hover:text-green-400"
          >
            resolve tx: {call.oracleResolveTx.slice(0, 18)}… →
          </a>
        )}
        {call.xPostUrl && (
          <a
            href={call.xPostUrl}
            target="_blank" rel="noopener noreferrer"
            className="text-neutral-500 hover:text-neutral-300"
          >
            @arke_ai →
          </a>
        )}
      </div>
    </div>
  );
}
