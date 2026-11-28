import { expect, it } from 'vitest';
import registration from '../../../../web/registrations/L14';

it('keeps private routes, bilingual keys and bounded versioned operations unique', () => {
  expect(registration.routes.map(route => route.path)).toEqual(['/offers', '/brand-quotes', '/repair-quotes']);
  expect(Object.keys(registration.dictionaries.en).sort()).toEqual(Object.keys(registration.dictionaries.ar).sort());
  const seen = new Set<string>();
  for (const endpoint of registration.gateway) {
    expect(endpoint.service).toBe('pricing');
    expect(endpoint.path).toMatch(/^\/v1\/[a-z-]+(?:\/(?:[a-z-]+|:[a-z]+))*$/);
    expect(endpoint.roles).not.toContain('public');
    expect(endpoint.maxBodyBytes).toBe(64 * 1024);
    expect(endpoint.maxResponseBytes).toBe(2 * 1024 * 1024);
    for (const method of endpoint.methods) {
      const key = method + ' ' + endpoint.path;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
  }
  expect(registration.slots.map(slot => slot.id)).toEqual(['l14-watch-offer']);
  expect(registration.gateway.some(endpoint => endpoint.path.startsWith('/internal/'))).toBe(false);
});
