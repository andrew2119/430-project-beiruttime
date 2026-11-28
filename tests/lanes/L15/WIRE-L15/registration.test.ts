import { expect, test } from '../../../../web/node_modules/vitest/dist/index.js';
import registration from '../../../../web/registrations/L15';
import prior from '../../../../web/registrations/L08';

test('preserves version-one boundaries and scoped operations', () => {
  expect(registration.lane).toBe('L15');
  expect(Object.keys(registration.dictionaries.en).sort()).toEqual(Object.keys(registration.dictionaries.ar).sort());
  const all = [...prior.gateway, ...registration.gateway];
  const keys = all.flatMap(endpoint => endpoint.methods.map(method => `${endpoint.service}:${method}:${endpoint.path}`));
  expect(new Set(keys).size).toBe(keys.length);
  expect(registration.routes).toEqual([{path:'/business/customizations',roles:['brand'],area:'seller'}]);
  for (const endpoint of registration.gateway) {
    expect(endpoint.service).toBe('catalog');
    expect(endpoint.path.startsWith('/v1/')).toBe(true);
    expect(endpoint.path).not.toMatch(/\.\.|[?#]/);
    if (endpoint.roles.includes('public' as never)) {
      expect(endpoint.methods).toEqual(['GET']);
      expect(endpoint.path).toBe('/v1/brands/:id/compatibility');
    }
  }
  expect(registration.gateway.some(endpoint => endpoint.path.endsWith('/corrections'))).toBe(false);
});
