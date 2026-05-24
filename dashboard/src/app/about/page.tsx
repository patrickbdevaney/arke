export const metadata = {
    title: "About — ARKE",
};

export default function AboutPage() {
    return (
        <main className="bg-black min-h-screen font-data">
            <div className="border-b border-neutral-800 px-4 py-2 flex gap-4 text-xs">
                <a href="/" className="text-amber-400 font-bold">ARKE</a>
                <span className="text-neutral-600">/</span>
                <span className="text-neutral-400">about</span>
            </div>

            <div className="px-4 py-8 max-w-4xl mx-auto">
                <h1 className="text-2xl text-amber-400 font-bold mb-6">
                    What Arke is
                </h1>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 text-xs text-neutral-400">
                    <div>
                        <div className="text-neutral-200 mb-2 font-data">WHAT ARKE IS</div>
                        <p className="leading-relaxed font-prose">
                            An autonomous AI agent that monitors Polymarket every 6 hours,
                            generates calibrated probability estimates using a multi-agent
                            council, and logs every prediction to an immutable onchain oracle
                            on Arc testnet. Operating since May 18 2026 with zero human
                            intervention.
                        </p>
                    </div>
                    <div>
                        <div className="text-neutral-200 mb-2 font-data">THE MOAT</div>
                        <p className="leading-relaxed font-prose">
                            A permanently growing correctness ledger: every prediction is
                            signed, staked, and resolved onchain. The track record compounds
                            daily and cannot be retroactively manufactured. The crowd
                            distributes what it thinks; Arke documents whether the crowd was
                            wrong.
                        </p>
                    </div>
                    <div>
                        <div className="text-neutral-200 mb-2 font-data">REVENUE</div>
                        <p className="leading-relaxed font-prose">
                            Polymarket builder fees (0.5%) accrue on fills from orders placed
                            through Arke&apos;s on-site trade widget — no funds at risk on
                            Arke&apos;s side. Intelligence feed available via x402
                            micropayments at feed.arke.live:8402. Institutional subscription
                            tier in development.
                        </p>
                    </div>
                </div>

                <div className="mt-10 border-t border-neutral-900 pt-6 flex flex-wrap gap-x-6 gap-y-2 text-xs text-neutral-700">
                    <a href="/" className="hover:text-amber-500">← Home</a>
                    <a href="/oracle" className="hover:text-amber-500">Oracle →</a>
                    <a href="/track-record" className="hover:text-amber-500">Track record →</a>
                    <a href="/calibration" className="hover:text-amber-500">Calibration →</a>
                    <a href="https://x.com/arke_ai" target="_blank" rel="noopener noreferrer"
                       className="hover:text-amber-500">@arke_ai →</a>
                </div>
            </div>
        </main>
    );
}
