import { headers } from "next/headers";

export const revalidate = 300;

type Market = {
  conditionId: string;
  question: string;
  probabilityPct: number;
  volume24hr: number;
  endDateIso: string;
  betUrl: string;
  eventSlug: string;
};

async function getFeed(): Promise<Market[]> {
  const h = headers();
  const host = h.get("host") ?? "localhost:3000";
  const proto =
    h.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  try {
    const r = await fetch(`${proto}://${host}/api/feed`, {
      next: { revalidate: 300 },
    });
    if (!r.ok) return [];
    return (await r.json()) as Market[];
  } catch {
    return [];
  }
}

function ProbabilityBar({ pct }: { pct: number }) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="w-full h-1.5 bg-neutral-800 rounded">
      <div
        className="h-1.5 bg-amber rounded transition-all"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}

function MarketCard({ m }: { m: Market }) {
  return (
    <div className="border border-border bg-panel p-4 rounded hover:border-amber-dim transition-colors flex flex-col gap-3">
      <div className="flex justify-between items-start gap-3">
        <div className="text-sm text-neutral-200 leading-snug">{m.question}</div>
        <div className="text-amber font-bold text-2xl tabular-nums shrink-0">
          {m.probabilityPct}%
        </div>
      </div>
      <ProbabilityBar pct={m.probabilityPct} />
      <div className="flex justify-between text-xs">
        <span className="text-terminal-green">
          ${m.volume24hr.toLocaleString()} 24h
        </span>
        <span className="text-terminal-muted">
          ends {m.endDateIso ? m.endDateIso.slice(0, 10) : "—"}
        </span>
      </div>
      <a
        href={`https://${m.betUrl}`}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block text-center bg-amber text-bg font-bold px-3 py-2 rounded text-sm hover:bg-amber-dim transition-colors"
      >
        Bet on Polymarket →
      </a>
    </div>
  );
}

function StatsBar({ count }: { count: number }) {
  return (
    <header className="border-b border-border bg-panel sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
        <span className="text-amber font-bold">ARKE</span>
        <span className="text-neutral-400">
          autonomous prediction market intelligence
        </span>
        <span className="text-terminal-muted">|</span>
        <span>
          <span className="text-amber tabular-nums">{count}</span>{" "}
          <span className="text-neutral-400">markets surfaced</span>
        </span>
        <span className="text-terminal-muted">|</span>
        <a
          className="text-terminal-green hover:underline"
          href="https://x.com/arke_ai"
          target="_blank"
          rel="noopener noreferrer"
        >
          @arke_ai
        </a>
      </div>
    </header>
  );
}

export default async function Page() {
  const feed = await getFeed();
  return (
    <main>
      <StatsBar count={feed.length} />
      <div className="max-w-6xl mx-auto px-4 py-6">
        <h1 className="text-amber text-lg mb-4">
          // live feed — top non-sports markets, 20-80% probability
        </h1>
        {feed.length === 0 ? (
          <div className="text-terminal-muted text-sm">
            No actionable markets right now. Feed refreshes every 5 minutes.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {feed.map((m) => (
              <MarketCard key={m.conditionId} m={m} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
