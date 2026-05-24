import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Arke — autonomous prediction market intelligence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image() {
  // Fetch track record stats (public custom domain — not the protected
  // per-deployment URL). Falls back to baked-in values on any error.
  let nTotal = 15, nResolved = 2, accuracyPct = 50, brierIndex = 2290;
  try {
    const r = await fetch(
      "https://arke.live/api/intelligence",
      { next: { revalidate: 300 } }
    );
    if (r.ok) {
      const d = await r.json();
      if (d.trackRecord) {
        nTotal = d.trackRecord.nTotal;
        nResolved = d.trackRecord.nResolved;
        accuracyPct = d.trackRecord.accuracyPct;
        brierIndex = d.trackRecord.brierIndex;
      }
    }
  } catch {}

  return new ImageResponse(
    (
      <div
        style={{
          background: "#000000",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          padding: "60px",
          fontFamily: "monospace",
          border: "1px solid #262626",
        }}
      >
        {/* (Scanline gradient omitted — Satori, the engine behind ImageResponse,
            can't parse repeating-linear-gradient and fails the whole render.) */}

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <span style={{ color: "#F59E0B", fontSize: 48, fontWeight: 700,
                         letterSpacing: "0.15em" }}>
            ARKE
          </span>
          <span style={{ color: "#525252", fontSize: 24 }}>|</span>
          <span style={{ color: "#737373", fontSize: 20 }}>
            autonomous prediction market intelligence
          </span>
        </div>

        {/* Big stats */}
        <div style={{ display: "flex", gap: "60px", marginTop: "60px" }}>
          {[
            { value: String(nTotal), label: "PREDICTIONS" },
            { value: String(nResolved), label: "RESOLVED" },
            { value: `${accuracyPct}%`, label: "ACCURACY", accent: true },
            { value: String(brierIndex), label: "BRIER" },
          ].map(({ value, label, accent }) => (
            <div key={label} style={{ display: "flex", flexDirection: "column" }}>
              <span style={{
                color: accent ? "#FBBF24" : "#F5F5F5",
                fontSize: 72,
                fontWeight: 700,
                lineHeight: 1,
                fontVariantNumeric: "tabular-nums",
              }}>
                {value}
              </span>
              <span style={{ color: "#525252", fontSize: 16,
                             marginTop: "8px", letterSpacing: "0.1em" }}>
                {label}
              </span>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div style={{ marginTop: "auto", display: "flex",
                      justifyContent: "space-between", alignItems: "flex-end" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            <span style={{ color: "#404040", fontSize: 14 }}>
              operating autonomously since 2026-05-18
            </span>
            <span style={{ color: "#404040", fontSize: 14 }}>
              every prediction logged immutably on Arc testnet
            </span>
          </div>
          <span style={{ color: "#292929", fontSize: 14 }}>
            arke.live
          </span>
        </div>
      </div>
    ),
    { ...size }
  );
}
