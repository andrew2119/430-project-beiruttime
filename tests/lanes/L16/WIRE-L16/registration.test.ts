import { describe, expect, it } from 'vitest';
import l16, { lookupL16Operation, type L16Operation } from '../../../../web/registrations/L16';
import l09 from '../../../../web/registrations/L09';
import l10 from '../../../../web/registrations/L10';
import manifest from '../../../../contracts/registrations/L16.json';
import type { Registration } from '../../../../web/registry-types';

const entries: Registration[] = [l09, l10, l16];

describe('L16 composition', () => {
  it('keeps activation deferred until every shared reader and subscription is ready', () => {
    const runtime = manifest.wiring.runtime_integration;
    expect(runtime.state).toBe('unavailable');
    expect(runtime.connected_proof).toBe('deferred');
    expect(runtime.destinations_enabled).toBe(false);
    expect(runtime.prerequisites.map(item => item.reader)).toEqual(runtime.required_readers);
    expect(runtime.prerequisites.every(item => item.state === 'deferred' && item.owner === 'runtime-steward')).toBe(true);
    expect(runtime.activation_policy).toBe('require-all-readers-and-subscriptions-before-enabling-destinations');
    expect(manifest.wiring.delivery.enabled).toBe(false);
  });

  it('publishes the complete shared discovery prerequisite without substituting local success', () => {
    const discovery = manifest.wiring.runtime_integration.discovery_contract;
    expect(discovery.schema_version).toBe('lane-discovery.v1');
    expect(discovery.accepted_lanes).toEqual(Array.from({ length: 26 }, (_, lane) => `L${String(lane).padStart(2, '0')}`));
    expect(discovery.unsupported_lane).toBe('reject');
    expect(discovery.absent_registration).toBe('omit');
    expect(discovery.absent_compose_fragment).toBe('unset-inherited-fragment-variable');
    expect(discovery.generated_indexes).toBe('uncommitted');
    expect(discovery.acceptance).toBe('production-readers-must-pass-discovery-regressions');
  });

  it('preserves the existing public registrations', () => {
    expect(l16.routes).toEqual([]);
    expect(l16.gateway).toEqual([]);
    expect(l16.slots).toEqual([]);
    expect(l16.namespace).toBe('lane-wiring');
    expect(Object.keys(l16.dictionaries.en)).toEqual(Object.keys(l16.dictionaries.ar));
    expect(new Set(entries.flatMap(entry => entry.routes.map(route => route.path))).size)
      .toBe(entries.flatMap(entry => entry.routes).length);
  });

  it.each(Object.entries(manifest.wiring.operations))('resolves only the declared provider for %s', (id, operation) => {
    const result = lookupL16Operation(id as L16Operation, entries);
    expect(result?.path).toBe(operation.path);
    expect(result?.methods).toEqual([operation.method]);
    expect(result?.roles).not.toContain('public');
    expect(result?.maxBodyBytes).toBeGreaterThan(0);
    expect(result?.maxResponseBytes).toBeLessThanOrEqual(16 * 1024 * 1024);
  });

  it('fails closed for absent, duplicate and competing providers', () => {
    expect(lookupL16Operation('intake.read.v1', [])).toBeUndefined();
    expect(lookupL16Operation('intake.read.v1', [...entries, l09])).toBeUndefined();
    expect(lookupL16Operation('intake.read.v1', [...entries, { ...l09, lane: 'L25' }])).toBeUndefined();
    expect(lookupL16Operation('unknown' as L16Operation, entries)).toBeUndefined();
  });

  it.each([0, -1, 1.5, 16777217, Number.NaN])('rejects an invalid byte budget %s', maxBodyBytes => {
    const changed: Registration = { ...l09, gateway: l09.gateway.map(endpoint => ({ ...endpoint, maxBodyBytes })) };
    expect(lookupL16Operation('intake.read.v1', [changed])).toBeUndefined();
  });

  it('rejects public authority and cookie forwarding', () => {
    for (const patch of [{ roles: ['public'] }, { forwardCookies: ['session'] }, { roles: [] }]) {
      const changed = { ...l09, gateway: l09.gateway.map(endpoint => ({ ...endpoint, ...patch })) } as Registration;
      expect(lookupL16Operation('intake.read.v1', [changed])).toBeUndefined();
    }
  });

  it('isolates concurrent lookup results from registered permissions', async () => {
    const results = await Promise.all(Array.from({ length: 40 }, async () => lookupL16Operation('intake.read.v1', entries)));
    results[0]!.roles.length = 0;
    expect(results[1]!.roles).toEqual(['dealer', 'brand']);
    expect(lookupL16Operation('intake.read.v1', entries)?.roles).toEqual(['dealer', 'brand']);
  });

  it('retains one action reference through uncertain and duplicate results', () => {
    const fixtures = manifest.wiring.fixtures;
    expect(new Set(fixtures.map(item => item.operation_id)).size).toBe(1);
    expect(fixtures.find(item => item.scenario === 'duplicate')).toEqual({ ...fixtures[0], scenario: 'duplicate' });
    expect(fixtures.find(item => item.scenario === 'lost-response')?.state).toBe('pending');
    expect(manifest.wiring.delivery.enabled).toBe(false);
    expect(manifest.wiring.result_policy.authority).toBe('current-provider-only');
  });
});
