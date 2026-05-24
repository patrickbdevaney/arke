// Resolve the base URL for server-side self-fetches of /api/intelligence.
//
// The per-deployment VERCEL_URL host is gated by Vercel Deployment Protection
// (returns 401), so a server component fetching its own VERCEL_URL fails and
// the page renders empty. The production custom domain (arke.live) is public,
// so we target it directly. Override with NEXT_PUBLIC_SITE_URL if the public
// domain ever changes.
export function siteBase(): string {
    const explicit = process.env.NEXT_PUBLIC_SITE_URL;
    if (explicit) return explicit.replace(/\/$/, "");
    // Any Vercel environment (preview or production) → use the public domain.
    if (process.env.VERCEL) return "https://arke.live";
    return "http://localhost:3000";
}
