import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { validatedBrowserOrigin } from '../gateway/origin';

beforeEach(() => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', 'https://beirut.test,http://localhost:33101');
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'false');
});
afterEach(() => vi.unstubAllEnvs());
function request(origin?: string, headers: Record<string, string> = {}) {
  return new Request('http://0.0.0.0:3000/api/web/v1/identity/v1/auth/login', {
    headers: { ...(origin === undefined ? {} : { Origin: origin }), ...headers },
  });
}

it.each(['https://beirut.test', 'http://localhost:33101'])('accepts configured public origin %s independently of the bind origin', origin => {
  expect(validatedBrowserOrigin(request(origin))).toBe(origin);
});
it.each([undefined, 'null', 'https://foreign.test', 'http://0.0.0.0:3000', 'https://beirut.test.attacker.test',
  'https://beirut.test/', 'https://beirut.test/path', 'https://beirut.test?query', 'https://user@beirut.test',
  'https://beirut.test#fragment', 'https://beirut.test,https://foreign.test', 'file://beirut.test', '*'])('rejects absent, foreign or non-origin value %s', origin => {
  expect(validatedBrowserOrigin(request(origin))).toBeNull();
});
it('does not infer trust from Host or forwarded headers by default', () => {
  expect(validatedBrowserOrigin(request('https://foreign.test', {
    Host: 'foreign.test', 'X-Forwarded-Host': 'foreign.test', 'X-Forwarded-Proto': 'https',
  }))).toBeNull();
});
it('treats an explicitly empty list as fail-closed and an unset list as local development defaults', () => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', '');
  expect(validatedBrowserOrigin(request('http://localhost:3000'))).toBeNull();
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', undefined);
  expect(validatedBrowserOrigin(request('http://localhost:3000'))).toBe('http://localhost:3000');
  expect(validatedBrowserOrigin(request('http://127.0.0.1:3000'))).toBe('http://127.0.0.1:3000');
  expect(validatedBrowserOrigin(request('http://localhost:33101'))).toBeNull();
});
it('canonicalizes configured origins without accepting wildcards or URL paths', () => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', ' https://BEIRUT.test:443/, https://foreign.test/path, *, null ');
  expect(validatedBrowserOrigin(request('https://beirut.test'))).toBe('https://beirut.test');
  expect(validatedBrowserOrigin(request('https://foreign.test'))).toBeNull();
});
it('accepts a single advertised public origin only with exact proxy opt-in', () => {
  vi.stubEnv('BT_PUBLIC_WEB_ORIGINS', '');
  const forwarded = request('https://beirut.up.railway.app', { 'X-Forwarded-Host': 'beirut.up.railway.app', 'X-Forwarded-Proto': 'https' });
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', '1');
  expect(validatedBrowserOrigin(forwarded)).toBeNull();
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'true');
  expect(validatedBrowserOrigin(forwarded)).toBe('https://beirut.up.railway.app');
});
it.each([
  { host: 'beirut.up.railway.app,attacker.test', proto: 'https' },
  { host: 'beirut.up.railway.app', proto: 'https,http' },
  { host: '', proto: 'https' }, { host: 'beirut.up.railway.app', proto: '' },
  { host: 'beirut.up.railway.app', proto: 'ftp' },
  { host: 'user@beirut.up.railway.app', proto: 'https' },
  { host: 'beirut.up.railway.app/path', proto: 'https' },
  { host: 'beirut.up.railway.app?query', proto: 'https' },
  { host: 'beirut.up.railway.app', proto: 'http' },
])('rejects incomplete, chained, malformed or mismatched forwarded authority $host/$proto', ({ host, proto }) => {
  vi.stubEnv('BT_TRUST_FORWARDED_ORIGIN', 'true');
  expect(validatedBrowserOrigin(request('https://beirut.up.railway.app', { 'X-Forwarded-Host': host, 'X-Forwarded-Proto': proto }))).toBeNull();
});
