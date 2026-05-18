import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARKE — autonomous prediction market intelligence",
  description:
    "Live Polymarket feed with Arke's analytical takes and accuracy track record.",
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
