import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://arke.live"),
  title: "ARKE — autonomous prediction market intelligence",
  description:
    "Arke autonomously monitors Polymarket, generates calibrated probability estimates that diverge from consensus, and logs every prediction to an immutable onchain oracle. Verified track record since May 18 2026.",
  openGraph: {
    title: "ARKE — autonomous prediction market intelligence",
    description:
      "Every prediction signed, staked, and logged to Arc testnet. Verifiable track record since May 18 2026.",
    url: "https://arke.live",
    siteName: "Arke",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ARKE — autonomous prediction market intelligence",
    description: "Every prediction onchain. Track record since May 18 2026.",
    site: "@arke_ai",
  },
  // Favicons are provided by the App Router file conventions in this directory
  // (favicon.ico, icon.png, apple-icon.png) — Next injects the correct <link>
  // tags automatically. No manual `icons` entry needed (the old "/favicon.png"
  // reference 404'd — no such file existed).
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="font-mono bg-black text-neutral-200 min-h-screen">
        {children}
      </body>
    </html>
  );
}