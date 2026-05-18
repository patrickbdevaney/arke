import { NextResponse } from "next/server";

export const revalidate = 300;

const SPORTS_KEYWORDS = [
  "vs.", "vs ", "O/U", "Spread:", "Map ", "BO3", "BO5", "BO7",
  "Pistons", "Cavaliers", "Spurs", "Lakers", "Dodgers", "Red Sox",
  "Braves", "Angels", "Sinner", "Medvedev", "Aston Villa", "Liverpool",
  "Counter-Strike", "CS:GO", "CS2", "LoL", "League of Legends",
  "Dota", "Valorant", "Eurovision", "FIFA World Cup", "FIFA",
  "Natus Vincere", "Scheffler", "PGA", "Masters", "Wimbledon",
  "Celtics", "Knicks", "Heat", "Warriors", "Nuggets", "Yankees",
  "Mets", "Cubs", "Padres", "Giants", "NBA", "NFL", "MLB", "NHL",
  "UFC", "Formula 1", "F1 ", "Grand Prix", "Champions League",
  "Premier League", "La Liga", "Bundesliga", "Serie A",
];

function isSports(q: string): boolean {
  if (!q) return false;
  const ql = q.toLowerCase();
  return SPORTS_KEYWORDS.some((kw) => ql.includes(kw.toLowerCase()));
}

type GammaMarket = {
  conditionId?: string;
  question?: string;
  slug?: string;
  lastTradePrice?: number | string;
  volume24hr?: number | string;
  endDateIso?: string;
  events?: Array<{ slug?: string }>;
};

export async function GET() {
  const builderAddr = process.env.POLY_BUILDER_ADDRESS ?? "";

  let markets: GammaMarket[] = [];
  try {
    const r = await fetch(
      "https://gamma-api.polymarket.com/markets?active=true&limit=100&order=volume24hr&ascending=false",
      { next: { revalidate: 300 } }
    );
    if (!r.ok) {
      return NextResponse.json([], { status: 200 });
    }
    markets = (await r.json()) as GammaMarket[];
  } catch {
    return NextResponse.json([], { status: 200 });
  }

  const cleaned = markets
    .map((m) => {
      const vol = Number(m.volume24hr ?? 0) || 0;
      const price = Number(m.lastTradePrice ?? 0) || 0;
      const pct = Math.round(price * 100);
      const q = m.question ?? "";
      return { m, vol, pct, q };
    })
    .filter(({ vol, pct, q }) => vol > 50_000 && pct >= 20 && pct <= 80 && !isSports(q))
    .sort((a, b) => b.vol - a.vol)
    .map(({ m, vol, pct, q }) => {
      const eventSlug = m.events?.[0]?.slug ?? m.slug ?? "";
      const ref = builderAddr ? `?ref=${builderAddr}` : "";
      const betUrl = `polymarket.com/event/${eventSlug}${ref}`;
      return {
        conditionId: m.conditionId ?? "",
        question: q,
        probabilityPct: pct,
        volume24hr: vol,
        endDateIso: m.endDateIso ?? "",
        betUrl,
        eventSlug,
      };
    });

  return NextResponse.json(cleaned);
}
