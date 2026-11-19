import type { NextConfig } from 'next';
const config: NextConfig = {
  output: 'standalone',
  outputFileTracingRoot: process.cwd().replace(/[/\\]web$/, ''),
  transpilePackages: ['@beirut-time/contracts-core','@beirut-time/i18n','@beirut-time/ui'],
  poweredByHeader: false,
  agentRules: false,
  // Preserve the raw loopback origin: NextURL normalizes 127.0.0.1 to localhost,
  // which otherwise turns an internal locale rewrite into a recursive HTTP proxy.
  skipProxyUrlNormalize: true,
  experimental: { cpus: 2 },
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
    ] }, { source: '/sw.js', headers: [{ key: 'Cache-Control', value: 'no-cache' }] }];
  },
};
export default config;
