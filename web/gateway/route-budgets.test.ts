import { afterEach, expect, it, vi } from 'vitest';
import { gatewayRegistrations } from '@/registry-loader';
import { Dependency } from './dependency';
import { routeBudget, routeBudgets } from './route-budgets';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function delayedResponse(delay: number, response: Response) {
  vi.useFakeTimers();
  vi.spyOn(AbortSignal, 'timeout').mockImplementation(ms => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), ms);
    return controller.signal;
  });
  const upstream = vi.fn((_url: URL, { signal }: RequestInit) => new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => resolve(response), delay);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(signal.reason);
    }, { once: true });
  }));
  vi.stubGlobal('fetch', upstream);
  return upstream;
}

// The existing credential and publication cases have independent coverage.
const addedRoutes = routeBudgets.flatMap(([service, method, path, budget]) =>
  typeof path === 'string' ? [{ service, method, path, budget }] : [],
);

it.each([
  ['GET', '/v1/listings/test-record/report-subject', 11200],
  ['GET', '/v1/listings/test-record/photo-credits', undefined],
  ['GET', '/v1/listings/test-record', 4900],
  ['GET', '/v1/discovery/watches', 2150],
  ['GET', '/v1/discovery/watches/test-record', 5250],
  ['GET', '/v1/discovery/watches/test-record/auction', 5250],
  ['POST', '/v1/request-drafts', 34600],
  ['GET', '/v1/request-drafts', 19400],
  ['PATCH', '/v1/request-drafts/test-record', 37600],
  ['GET', '/v1/seller/listings/test-record/media', 9700],
  ['GET', '/v1/seller/listings', 17700],
  ['POST', '/v1/seller/listings', 32200],
  ['GET', '/v1/seller/listings/test-record', 8700],
  ['PUT', '/v1/seller/listings/test-record', 29700],
  ['POST', '/v1/seller/listings/test-record/media', 49700],
  ['POST', '/v1/brand-options/configurations/test-record/references', 37700],
  ['PUT', '/v1/seller/listings/test-record/gallery', 32700],
  ['DELETE', '/v1/seller/listings/test-record/media/test-asset', 35700],
  ['GET', '/v1/brand-options/configurations/test-record/references/test-reference', 5700],
  ['GET', '/v1/brand-options/brands', 3900],
  ['GET', '/v1/brand-options/brands/test-brand', 9200],
  ['GET', '/v1/brand-options/configurations', 7700],
  ['GET', '/v1/brand-options/configurations/test-record', 22700],
  ['PUT', '/v1/brand-options/brands/test-brand/dial/test-option', 37700],
  ['PUT', '/v1/brand-options/configurations/test-record/dial', 55700],
  ['PUT', '/v1/options/movement/test-record', 28200],
  ['POST', '/v1/options/movement/selections', 34200],
  ['GET', '/v1/options/movement', 9700],
  ['GET', '/v1/options/movement/test-record', 6700],
  ['GET', '/v1/options/movement/selections/current', 6700],
] as const)('assigns Catalog %s %s the expected override (%s)', (method, path, budget) => {
  expect(routeBudget('catalog', method, path)).toBe(budget);
});

it('budgets private-seller evidence submission and live application reads', () => {
  expect(routeBudget('identity', 'POST', '/v1/private-seller/applications')).toBe(39200);
  expect(routeBudget('identity', 'GET', '/v1/private-seller/applications/me')).toBe(18200);
});

it.each([
  ['POST', '/v1/businesses', 59200],
  ['PATCH', '/v1/businesses/test-record', 298800],
  ['GET', '/v1/businesses/test-record', undefined],
  ['POST', '/v1/memberships', 86200],
  ['PATCH', '/v1/memberships/test-record', 89200],
  ['GET', '/v1/businesses/test-record/memberships', 29200],
  ['POST', '/v1/accounts/recovery', 44200],
  ['POST', '/v1/accounts/logout', 21200],
  ['POST', '/v1/demo-entry/sessions', 102200],
  ['GET', '/v1/demo-entry/sessions', undefined],
  ['GET', '/v1/accounts/logout', undefined],
  ['GET', '/v1/accounts/recovery', undefined],
  ['POST', '/v1/contacts/challenges', 59200],
  ['POST', '/v1/contacts/challenges/test-record/verify', 62200],
  ['POST', '/v1/private-reviews', 80200],
  ['POST', '/v1/private-reviews/test-record/verdict', 86200],
  ['POST', '/v1/private-reviews/test-record/reassign', 71200],
  ['GET', '/v1/private-reviews', 23200],
  ['GET', '/v1/private-reviews/mine', 23200],
  ['GET', '/v1/private-reviews/test-record', 53200],
  ['GET', '/v1/private-reviews/test-record/evidence', 44200],
] as const)('assigns Identity %s %s the expected override (%s)', (method, path, budget) => {
  expect(routeBudget('identity', method, path)).toBe(budget);
});

it.each([
  ['catalog', '/v1/seller/listings', 6201, 32200, 201],
  ['service-operations', '/v1/intake/records/test-record/evidence', 6001, 47000, 201],
] as const)('returns %s %s receipts after %s ms within the %s ms deadline', async (
  service, path, delay, budget, status,
) => {
  const receipt = { operation_id: 'test-operation', revision: 2 };
  const upstream = delayedResponse(delay, Response.json(receipt, { status }));
  const client = new Dependency(service, 'https://service.test');
  const pending = client.request('POST', path, 'test-request', {
    headers: { 'Idempotency-Key': receipt.operation_id },
  });
  expect(AbortSignal.timeout).toHaveBeenCalledExactlyOnceWith(budget);
  await vi.advanceTimersByTimeAsync(delay);
  const response = await pending;
  expect(response).toBeInstanceOf(Response);
  expect((response as Response).status).toBe(status);
  expect(await (response as Response).json()).toEqual(receipt);
  expect(upstream).toHaveBeenCalledTimes(1);
  expect(new Headers(upstream.mock.calls[0][1].headers).get('Idempotency-Key')).toBe(receipt.operation_id);
});

it.each([
  ['POST', '/v1/quotes', 28600],
  ['POST', '/v1/quotes/test-record/review', 37600],
  ['GET', '/v1/quotes', 7400],
  ['GET', '/v1/quotes/test-record', 7400],
] as const)('assigns Pricing %s %s a deadline of %s ms', (method, path, budget) => {
  expect(routeBudget('pricing', method, path)).toBe(budget);
});

it.each([
  ['GET', '/v1/consents', 10400],
  ['POST', '/v1/consents', 43000],
  ['POST', '/v1/consents/test-record/withdraw', 34400],
  ['GET', '/v1/consents/test-record/evidence/test-evidence', 26600],
] as const)('assigns Eligibility %s %s a deadline of %s ms', (method, path, budget) => {
  expect(routeBudget('eligibility', method, path)).toBe(budget);
});

it.each([
  ['/v1/seller/auctions', 10400],
  ['/v1/my-bids', 10400],
  ['/v1/prebid-operations/test-operation.1', 7400],
  ['/v1/auctions/test-record/my-prebid', 7400],
  ['/v1/auctions/test-record/operations/test-operation', 7400],
  ['/v1/auction-operations/by-key/test-operation.1', 7400],
  ['/v2/prebid-operations/test-operation.1', 10400],
  ['/v2/auctions/test-record/my-prebid', 10400],
  ['/v2/seller/auctions/test-record/policy', 10400],
  ['/v2/auctions/test-record/policy', 9200],
] as const)('assigns Auction GET %s the expected override (%s)', (path, budget) => {
  expect(routeBudget('auction', 'GET', path)).toBe(budget);
});

it.each([
  ['POST', '/v1/moderation/cases/test-record/claim', 31400],
  ['POST', '/v1/moderation/cases/test-record/release', 28400],
  ['POST', '/v1/moderation/cases/test-record/decisions', 34400],
  ['POST', '/v1/moderation/cases/test-record/appeals', 28400],
  ['GET', '/v1/moderation/cases', 10400],
  ['GET', '/v1/moderation/cases/test-record', 21400],
] as const)('assigns Trust %s %s the expected override (%s)', (method, path, budget) => {
  expect(routeBudget('trust', method, path)).toBe(budget);
});

it.each([
  ['POST', '/v1/reservations', 58600],
  ['GET', '/v1/orders', 7400],
  ['GET', '/v1/operations/test-record', 7400],
  ['GET', '/v1/orders/test-record', 12400],
  ['GET', '/v1/orders/test-record/intake', 12400],
  ['GET', '/v1/me/reservations', 12400],
] as const)('assigns Orders %s %s the expected override (%s)', (method, path, budget) => {
  expect(routeBudget('orders', method, path)).toBe(budget);
});

it.each([
  ['GET', '/v1/bid-notices', 7400],
  ['GET', '/v1/bid-notices/test-record', 8600],
  ['GET', '/v1/inbox', 16400],
  ['GET', '/v1/buying/readiness', 9800],
  ['PUT', '/v1/inbox/preferences', 25400],
  ['POST', '/v1/inbox/test-notice/read', 28400],
  ['POST', '/v1/inbox/test-notice/clear', 28400],
  ['GET', '/v1/inbox/preferences', 7400],
  ['GET', '/v1/buying/drafts', 7400],
  ['GET', '/v1/buying/drafts/test-record', 7400],
  ['POST', '/v1/buying/drafts/test-record/send', 7400],
  ['POST', '/v1/buying/drafts/test-record/accept', 7400],
] as const)('assigns Communications %s %s the expected override (%s)', (method, path, budget) => {
  expect(routeBudget('communications', method, path)).toBe(budget);
});

it.each([
  ['PUT', '/v1/directory/businesses/test-record', 28200],
  ['POST', '/v1/directory/choices', 31200],
  ['GET', '/v1/directory/businesses', 10150],
  ['GET', '/v1/directory/businesses/test-record', 6700],
  ['GET', '/v1/directory/providers/test-record', 6700],
  ['GET', '/v1/directory/choices/current', 6700],
] as const)('assigns service operations %s %s the expected override (%s)', (method, path, budget) => {
  expect(routeBudget('service-operations', method, path)).toBe(budget);
});

it.each([
  ['identity', 'PATCH', '/v1/businesses/test-record', 200000, 298800, 200],
  ['catalog', 'GET', '/v1/discovery/watches', 1201, 2150, 200],
  ['orders', 'POST', '/v1/orders/test-record/transitions', 31401, 39400, 200],
  ['orders', 'POST', '/v1/orders/test-record/intake', 37401, 45400, 200],
  ['auction', 'POST', '/v1/auctions', 9601, 53600, 200],
  ['auction', 'PATCH', '/v1/auctions/test-record/rules', 6001, 55000, 200],
  ['catalog', 'GET', '/v1/listings/test-record/report-subject', 6201, 11200, 200],
  ['service-operations', 'GET', '/v1/intake/records', 4801, 12800, 200],
  ['service-operations', 'GET', '/v1/intake/records/test-record', 7201, 12200, 200],
  ['service-operations', 'POST', '/v1/intake/records', 6001, 41000, 201],
  ['service-operations', 'PUT', '/v1/intake/records/test-record', 6001, 38000, 200],
  ['service-operations', 'GET', '/v1/intake/records/test-record/evidence', 4801, 12800, 200],
  ['service-operations', 'GET', '/v1/intake/evidence/test-evidence', 4801, 14800, 200],
] as const)('returns %s %s %s after the former deadline', async (service, method, path, delay, budget, status) => {
  const body = { id: 'test-record' };
  const upstream = delayedResponse(delay, Response.json(body, { status }));
  const client = new Dependency(service, 'https://service.test');
  const pending = client.request(method, path, 'test-request');

  expect(AbortSignal.timeout).toHaveBeenCalledExactlyOnceWith(budget);
  await vi.advanceTimersByTimeAsync(delay);
  const response = await pending;
  expect(response).toBeInstanceOf(Response);
  expect((response as Response).status).toBe(status);
  expect(await (response as Response).json()).toEqual(body);
  expect(upstream).toHaveBeenCalledTimes(1);
});

it.each([
  // Buyer workspace caps Identity at 300 ms and runs the 600 ms sources in parallel.
  ['communications', 'GET', '/v1/buyer-workspace'],
  // Payment capability checks Identity and returns the unreleased result.
  ['communications', 'POST', '/v1/buying/payment'],
  // Public publication, availability and directory reads each run one query.
  ['catalog', 'GET', '/v1/listings/test-record/publication'],
  ['orders', 'GET', '/v1/listings/test-record/availability'],
  ['orders', 'GET', '/v1/watches/test-record/availability'],
  ['identity', 'GET', '/v1/businesses'],
  // Auction quote preview checks the principal and returns the fixed-price requirement.
  ['pricing', 'POST', '/v1/auction-quotes'],
] as const)('keeps the standard deadline for %s %s %s', (service, method, path) => {
  expect(routeBudget(service, method, path)).toBeUndefined();
});

it.each([
  ...addedRoutes,
  { service: 'pricing', method: 'POST', path: '/v1/auction-quotes', budget: 1200 },
])('$service $method $path expires at $budget ms', async ({ service, method, path, budget }) => {
  const upstream = delayedResponse(budget + 1, Response.json({ state: 'succeeded' }));

  const route = path.replace(/:[A-Za-z][A-Za-z0-9_]*/g, 'test-record');
  const client = new Dependency(service, 'https://service.test');
  let settled = false;
  const result = client.request(method, route + '?view=current', 'test-request').then(response => {
    settled = true;
    return response;
  });
  expect(AbortSignal.timeout).toHaveBeenCalledExactlyOnceWith(budget);
  await vi.advanceTimersByTimeAsync(budget - 1);
  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  await expect(result).resolves.toEqual({ kind: 'unavailable', dependency: service });
  await vi.advanceTimersByTimeAsync(1);
  expect(upstream).toHaveBeenCalledTimes(1);
});

it.each([
  ['auction', '/v1/auctions/test-record/bids', 13201, 298800],
  ['auction', '/v1/auctions/test-record/maximum', 13201, 298800],
  ['trust', '/v1/moderation/reports', 4801, 33800],
] as const)('returns the receipt for %s %s after %s ms with a %s ms deadline', async (service, path, delay, budget) => {
  const receipt = { operation_id: 'test-operation', status: 'succeeded' };
  const status = service === 'trust' ? 201 : 200;
  const upstream = delayedResponse(delay, Response.json(receipt, { status }));
  const client = new Dependency(service, 'https://service.test');
  const pending = client.request('POST', path, 'test-request', {
    headers: { 'Idempotency-Key': receipt.operation_id },
  });
  expect(AbortSignal.timeout).toHaveBeenCalledExactlyOnceWith(budget);
  await vi.advanceTimersByTimeAsync(delay);
  const result = await pending;
  expect(result).toBeInstanceOf(Response);
  expect((result as Response).status).toBe(status);
  expect(await (result as Response).json()).toEqual(receipt);
  expect(upstream).toHaveBeenCalledTimes(1);
});

it('limits added budgets to registered service, method and path combinations', () => {
  const shape = (path: string) => path.replace(/:[A-Za-z][A-Za-z0-9_]*/g, ':parameter');
  const registered = gatewayRegistrations.flatMap(endpoint =>
    endpoint.methods.map(method => [endpoint.service, method, shape(endpoint.path)]),
  );
  for (const { service, method, path } of addedRoutes) {
    expect(registered).toContainEqual([service, method, shape(path)]);
  }
});
