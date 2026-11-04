import { afterEach, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from '../proxy';
import config from '../next.config';
afterEach(() => vi.unstubAllEnvs());

const origin = 'https://beirut.test';
it('preserves raw request URLs before proxy execution', () => {
  expect(config.skipProxyUrlNormalize).toBe(true);
});

it.each(['127.0.0.1', '[::1]'])('keeps a %s rewrite same-origin instead of recursively proxying localhost', hostname => {
  vi.stubEnv('__NEXT_NO_MIDDLEWARE_URL_NORMALIZE', '1');
  const origin = `http://${hostname}:3109`;
  const request = new NextRequest(origin + '/en/operations/moderation');
  expect(request.nextUrl.hostname).toBe('localhost');
  const response = proxy(request);
  expect(response.status).toBe(200);
  expect(response.headers.has('location')).toBe(false);
  expect(response.headers.get('x-middleware-rewrite')).toBe(origin + '/operations/moderation');
});

const nested = [
  { publicPath: '/en/operations/moderation', internalPath: '/operations/moderation', locale: 'en', cookie: 'ar' },
  { publicPath: '/ar/seller/dashboard', internalPath: '/seller/dashboard', locale: 'ar', cookie: 'en' },
];

it.each(nested)('rewrites $publicPath without a redirect or cookie locale override', proof => {
  const request = new NextRequest(origin + proof.publicPath + '?view=open', {
    headers: { Cookie: `bt-locale=${proof.cookie}`, 'x-bt-locale': 'spoofed', 'x-bt-path': '/spoofed' },
  });
  const response = proxy(request);
  expect(response.status).toBe(200);
  expect(response.headers.has('location')).toBe(false);
  expect(response.headers.get('x-middleware-rewrite')).toBe(origin + proof.internalPath + '?view=open');
  expect(response.headers.get('x-middleware-request-x-bt-locale')).toBe(proof.locale);
  expect(response.headers.get('x-middleware-request-x-bt-path')).toBe(proof.internalPath);
  expect(response.headers.get('Content-Security-Policy')).toContain("'nonce-");
});

it.each(nested)('does not redirect $publicPath to itself when nextUrl was normalized', proof => {
  const request = new NextRequest(origin + proof.publicPath + '?view=open', { headers: { Cookie: `bt-locale=${proof.locale}` } });
  request.nextUrl.pathname = proof.internalPath;
  expect(new URL(request.url).pathname).toBe(proof.publicPath);
  const response = proxy(request);
  expect(response.status).toBe(200);
  expect(response.headers.has('location')).toBe(false);
  expect(response.headers.get('x-middleware-rewrite')).toBe(origin + proof.internalPath + '?view=open');
});

it.each([
  { path: '/operations/moderation', cookie: 'en', destination: '/en/operations/moderation' },
  { path: '/seller/dashboard', cookie: 'ar', destination: '/ar/seller/dashboard' },
  { path: '/', cookie: 'invalid', destination: '/en' },
])('redirects only the missing locale prefix for $path', proof => {
  const response = proxy(new NextRequest(origin + proof.path + '?view=open', { headers: { Cookie: `bt-locale=${proof.cookie}` } }));
  expect(response.status).toBe(307);
  expect(response.headers.get('location')).toBe(origin + proof.destination + '?view=open');
  expect(response.headers.has('x-middleware-rewrite')).toBe(false);
});
