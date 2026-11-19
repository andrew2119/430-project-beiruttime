import { afterEach, expect, it, vi } from 'vitest';
import { Dependency } from '../../../../web/gateway/dependency';
afterEach(() => vi.unstubAllGlobals());
it('isolates dependency circuits and permits a single recovery probe', async () => {
  const fetch = vi.fn().mockRejectedValue(new Error('unavailable')); vi.stubGlobal('fetch', fetch);
  const first = new Dependency('auction', 'http://auction', 100, 1, 0);
  const second = new Dependency('pricing', 'http://pricing');
  for (let count = 0; count < 3; count++) expect(await first.get('/v1/read', 'stable')).toMatchObject({ kind: 'unavailable' });
  fetch.mockImplementation(() => Promise.resolve(Response.json({ state: 'pending' })));
  expect(await second.get('/v1/read', 'stable')).toBeInstanceOf(Response);
  const probe = first.get('/v1/read', 'stable');
  expect(await first.get('/v1/read', 'stable')).toMatchObject({ kind: 'unavailable' });
  expect(await probe).toBeInstanceOf(Response); expect(first.openedAt).toBe(0);
});
it('bounds response bytes and retains unavailable outcomes', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('oversized')));
  const client = new Dependency('auction', 'http://auction');
  expect(await client.request('POST', '/v1/command', 'same-operation', { maxResponseBytes: 2 })).toEqual({ kind: 'unavailable', dependency: 'auction' });
  expect(client.active).toBe(0);
});
it('expires a dependency deadline without confirming a command', async () => {
  vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('deadline')), { once: true });
  })));
  const client = new Dependency('auction', 'http://auction', 10);
  expect(await client.request('POST', '/v1/command', 'same-operation')).toMatchObject({ kind: 'unavailable' });
  expect(client.active).toBe(0);
});
