import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { Dependency } from './dependency';
import { forward } from './forward';
import listingEditor from '@/registrations/L03';

const { dependencies } = vi.hoisted(() => ({ dependencies: new Map() }));
vi.mock('@/registry-loader', () => ({ get gatewayRegistrations() { return listingEditor.gateway; } }));
vi.mock('@/lib/bff/status', () => ({
  dependencies, serviceNames: ['catalog', 'identity'], requestId: () => 'test-request',
  privateHeaders: () => ({ 'Cache-Control': 'no-store' }),
}));

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  dependencies.clear();
});

it.each([
  { method: 'POST', download: false, delay: 1272, budget: 49700, status: 201 },
  { method: 'POST', download: false, delay: 49701, budget: 49700, status: 503 },
  { method: 'GET', download: true, delay: 2501, budget: 12700, status: 200 },
  { method: 'GET', download: true, delay: 12701, budget: 12700, status: 503 },
  { method: 'GET', download: false, delay: 1201, budget: 1200, status: 503 },
])('Catalog $method (download: $download) after $delay ms returns $status', async ({ method, download, delay, budget, status }) => {
  vi.useFakeTimers();
  vi.spyOn(AbortSignal, 'timeout').mockImplementation(ms => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), ms);
    return controller.signal;
  });
  const photo = readFileSync(new URL('../public/icons/bt-192.png', import.meta.url));
  const evidence = new TextEncoder().encode('%PDF-1.7\n% test evidence\n%%EOF');
  const listingId = '00000000-0000-4000-8000-000000000001';
  const assetId = '00000000-0000-4000-8000-000000000002';
  const responseBody = JSON.stringify({
    asset_id: assetId,
    kind: 'public_photo',
    listing: { id: listingId, revision: 2 },
  }, null, 2);
  const upstream = vi.fn((_url: URL, { signal }: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(download
      ? new Response(evidence, { headers: { 'Content-Type': 'application/pdf' } })
      : new Response(responseBody, { status: 201, headers: { 'Content-Type': 'application/json' } })
    ), delay);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(signal.reason);
    }, { once: true });
  }));
  vi.stubGlobal('fetch', upstream);
  dependencies.set('catalog', new Dependency('catalog', 'https://catalog.test'));
  dependencies.set('identity', {
    request: async () => Response.json({ actor: { subject_id: 'test-seller' }, roles: ['private_seller'] }),
  });

  const path = method === 'GET' && !download
    ? ['v1', 'listings', listingId, 'photo-credits']
    : ['v1', 'seller', 'listings', listingId, 'media'];
  if (download) path.push(assetId);
  const result = forward(new Request('http://localhost:3000/api/web/v1/catalog/' + path.join('/') + '?kind=public_photo&public_safe=true', {
    method,
    headers: {
      Origin: 'http://localhost:3000', Authorization: 'Bearer test-session', 'Content-Type': 'image/png',
      'Idempotency-Key': 'test-photo-upload', 'If-Match': '"1"',
    },
    body: method === 'POST' ? new Uint8Array(photo) : undefined,
  }), { params: Promise.resolve({ service: 'catalog', path }) });
  await vi.advanceTimersByTimeAsync(delay);
  const response = await result;
  expect(response.status).toBe(status);
  if (status === 201) {
    expect(response.headers.get('Content-Type')).toBe('application/json');
    expect(await response.text()).toBe(responseBody);
  } else if (status === 200) {
    expect(response.headers.get('Content-Type')).toBe('application/pdf');
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(evidence);
  } else {
    expect((await response.json()).error.code).toBe('unavailable');
  }
  expect(AbortSignal.timeout).toHaveBeenCalledExactlyOnceWith(budget);
  expect(upstream).toHaveBeenCalledTimes(1);
  if (method === 'POST') {
    const [url, options] = upstream.mock.calls[0];
    expect(options.body).toEqual(new Uint8Array(photo));
    expect(new Headers(options.headers).get('Content-Type')).toBe('image/png');
    expect(url.searchParams.get('kind')).toBe('public_photo');
    expect(url.searchParams.get('public_safe')).toBe('true');
  }
});
