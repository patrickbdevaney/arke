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
  // French football
  "Toulouse", "Marseille", "Lyon", "Monaco", "Lens", "Rennes",
  "Nantes", "Strasbourg", "Montpellier", "Brest", "Ligue 1",
  // More sports
  "Eredivisie", "MLS", "ATP", "WTA",
  "Roland Garros", "US Open", "Australian Open", "Tour de France",
  "Superbowl", "Super Bowl", "March Madness", "World Series",
  "Stanley Cup", "NBA Finals", "cricket", "rugby",
  // Esports
  "CSGO", "Dota 2", "Overwatch", "StarCraft", "PUBG",
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
  if (!builderAddr) {
    console.warn("[Feed] POLY_BUILDER_ADDRESS not set — bet URLs missing attribution");
  }

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
    .filter(({ m, vol, pct, q }) => {
      if (vol <= 50_000 || pct < 20 || pct > 80 || isSports(q)) return false;
      // Filter out markets ending in the past
      if (m.endDateIso) {
        const endDate = new Date(m.endDateIso);
        const now = new Date();
        if (endDate < now) return false;
      }
      return true;
    })
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
