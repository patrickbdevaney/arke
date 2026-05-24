/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    // The /api/intelligence route reads public/traces/*.json via fs at
    // runtime. Vercel does not include public/ in a function bundle by
    // default, so trace reads would fail on ISR revalidation. Force them in.
    outputFileTracingIncludes: {
      "/api/intelligence": ["./public/traces/**/*"],
    },
  },
};

module.exports = nextConfig;
