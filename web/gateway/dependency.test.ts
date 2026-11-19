import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Dependency } from './dependency';

beforeEach(() => {
  vi.useFakeTimers();
  // Use the same clock for the deadline and the simulated upstream response.
  vi.spyOn(AbortSignal, 'timeout').mockImplementation(ms => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(new DOMException('Deadline exceeded', 'TimeoutError')), ms);
    return controller.signal;
  });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function delayedResponse(ms: number) {
  const upstream = vi.fn((_url: URL, options: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(Response.json({ accepted: true })), ms);
    options.signal!.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(options.signal!.reason);
    }, { once: true });
  }));
  vi.stubGlobal('fetch', upstream);
  return upstream;
}

it.each(['login', 'register', 'reauthenticate', 'password', 'reset', 'refresh'])('allows a 1.4 second credential operation: %s', async operation => {
  const upstream = delayedResponse(1400);
  const dependency = new Dependency('identity', 'https://identity.test');
  const pending = dependency.request('POST', `/v1/accounts/${operation}`, 'test-request', {
    headers: { 'Idempotency-Key': 'test-operation' }, body: '{}',
  });
  await vi.advanceTimersByTimeAsync(1400);
  const response = await pending;
  expect(response).toBeInstanceOf(Response);
  expect((response as Response).status).toBe(200);
  expect(await (response as Response).json()).toEqual({ accepted: true });
  expect(AbortSignal.timeout).toHaveBeenCalledWith(8000);
  expect(upstream).toHaveBeenCalledTimes(1);
  expect(new Headers(upstream.mock.calls[0][1].headers).get('Idempotency-Key')).toBe('test-operation');
  expect(dependency.active).toBe(0);
});

it.each([
  ['identity', 'GET', '/v1/accounts/me'],
  ['identity', 'GET', '/internal/v1/principal'],
  ['identity', 'POST', '/v1/accounts/logout'],
  ['identity', 'POST', '/v1/accounts/recovery'],
  ['catalog', 'POST', '/v1/accounts/login'],
  ['identity', 'GET', '/v1/accounts/login'],
])('retains the read budget for %s %s %s', async (service, method, path) => {
  const upstream = delayedResponse(1400);
  const dependency = new Dependency(service, 'https://service.test');
  let settled = false;
  const pending = dependency.request(method, path, 'test-request').then(result => { settled = true; return result; });
  await vi.advanceTimersByTimeAsync(1199);
  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(await pending).toEqual({ kind: 'unavailable', dependency: service });
  expect(AbortSignal.timeout).toHaveBeenCalledWith(1200);
  expect(upstream).toHaveBeenCalledTimes(1);
  expect(dependency.active).toBe(0);
});

it('bounds credential calls at eight seconds without retrying', async () => {
  const upstream = delayedResponse(9000);
  const dependency = new Dependency('identity', 'https://identity.test');
  let settled = false;
  const pending = dependency.request('POST', '/v1/accounts/login', 'test-request').then(result => { settled = true; return result; });
  await vi.advanceTimersByTimeAsync(7999);
  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(await pending).toEqual({ kind: 'unavailable', dependency: 'identity' });
  await vi.advanceTimersByTimeAsync(10000);
  expect(upstream).toHaveBeenCalledTimes(1);
  expect(dependency.active).toBe(0);
});
