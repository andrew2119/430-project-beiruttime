import { expect, it, vi } from 'vitest';
vi.mock('../../../../web/registry.generated', () => ({ registrations: [] }));
import { discoverGateway, validateRegistrations } from '../../../../web/registry-loader';
import type { Registration } from '../../../../web/registry-types';
const registration = (namespace = 'first'): Registration => ({
  lane: 'L12', namespace, routes: [], dictionaries: { en: {}, ar: {} },
  gateway: [{ service: 'auction', path: '/v2/auctions/:id', methods: ['GET'], roles: ['buyer'] }],
});
it('permits absent fragments and disjoint methods on an existing URL', () => {
  expect(validateRegistrations([])).toEqual([]);
  const second = registration('second');
  second.gateway![0].methods = ['POST'];
  expect(validateRegistrations([registration(), second])).toHaveLength(2);
});
it('emits equivalent operations once even with renamed parameters', () => {
  const second = registration('second');
  second.gateway![0].path = '/v2/auctions/:auctionId';
  expect(discoverGateway([registration(), second])).toEqual(registration().gateway);
});
it.each(['/v2/../private', '/v2/auctions?private=1', '/v2/auctions#private', '/v2//auctions', '/v2/auctions/%2fprivate', '//private'])('rejects unsafe path %s', path => {
  const value = registration(); value.gateway![0].path = path;
  expect(() => validateRegistrations([value])).toThrow();
});
it('rejects unbounded bytes and missing access declarations', () => {
  const value = registration(); value.gateway![0].maxResponseBytes = Infinity;
  expect(() => validateRegistrations([value])).toThrow();
  delete value.gateway![0].maxResponseBytes; value.gateway![0].roles = [];
  expect(() => validateRegistrations([value])).toThrow();
});
it('rejects duplicate routes, slots and namespaces', () => {
  expect(() => validateRegistrations([registration(), registration()])).toThrow('namespace');
  const first = registration(), second = registration('second'); second.gateway = [];
  first.routes = second.routes = [{ path: '/auctions', roles: ['public'], area: 'storefront' }];
  expect(() => validateRegistrations([first, second])).toThrow('URL');
  first.routes = second.routes = [];
  first.slots = second.slots = [{ id: 'history', target: 'watch.detail', load: async () => ({ default: () => null }) }];
  expect(() => validateRegistrations([first, second])).toThrow('slot');
});
it('preserves the first access rule and budgets without mutating fragments', () => {
  const first = registration(), second = registration('second');
  first.gateway![0].maxBodyBytes = 100;
  first.gateway![0].maxResponseBytes = 200;
  second.gateway![0].roles = ['public'];
  second.gateway![0].maxResponseBytes = 1000;
  second.gateway![0].methods = ['GET', 'POST'];
  expect(discoverGateway([first, second])).toEqual([
    first.gateway![0], { ...second.gateway![0], methods: ['POST'] },
  ]);
  expect(second.gateway![0].methods).toEqual(['GET', 'POST']);
});
