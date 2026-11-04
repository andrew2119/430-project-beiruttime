import { registrations } from './registry.generated';
import type { Area, Registration, Role } from './registry-types';
import type { Locale } from '@beirut-time/i18n';
export function validateRegistrations(entries: Registration[]) {
  const namespaces = new Set<string>(), paths = new Set<string>(), ids = new Set<string>(), slots = new Set<string>();
  for (const entry of entries) {
    if (!/^L(0[0-9]|1[01])$/.test(entry.lane) || !/^[a-z][a-z0-9-]*$/.test(entry.namespace) || namespaces.has(entry.namespace)) throw new Error('Invalid or duplicate registration namespace');
    namespaces.add(entry.namespace);
    if (Object.keys(entry.dictionaries.en).sort().join('|') !== Object.keys(entry.dictionaries.ar).sort().join('|')) throw new Error(`Translation keys differ in ${entry.namespace}`);
    for (const route of entry.routes) {
      if (!route.path.startsWith('/') || route.path.includes('..') || paths.has(route.path)) throw new Error(`Invalid or duplicate public URL: ${route.path}`);
      paths.add(route.path);
    }
    for (const nav of entry.navigation ?? []) { if (ids.has(nav.id)) throw new Error(`Duplicate navigation: ${nav.id}`); ids.add(nav.id); }
    for (const slot of entry.slots ?? []) { if (slots.has(slot.id)) throw new Error(`Duplicate slot: ${slot.id}`); slots.add(slot.id); }
    for (const endpoint of entry.gateway ?? []) {
      for(const budget of [endpoint.maxBodyBytes, endpoint.maxResponseBytes]) if(budget!==undefined && (!Number.isInteger(budget)||budget<1||budget>16*1024*1024)) throw new Error('Gateway byte budgets must be bounded to 16 MiB');
      if (!endpoint.path.startsWith('/v1/') || endpoint.path.includes('..') || endpoint.path.includes('?') || endpoint.path.includes('#')) throw new Error('Gateway requires a fixed versioned path');
    }
  }
  return entries;
}
const registered = validateRegistrations(registrations);
export const registeredRoutes = registered.flatMap(r => r.routes);
export const navigation = registered.flatMap(r => r.navigation ?? []).sort((a,b) => a.order-b.order);
export function navigationFor(area: Area, roles: Role[] = ['public']) { return navigation.filter(n => n.area === area && n.roles.some(r => r === 'public' || roles.includes(r))); }
export function hasRoute(path: string) { return registered.some(r => r.routes.some(route => route.path === path)); }
export function featureMessages(namespace: string, locale: Locale) { return registered.find(r => r.namespace === namespace)?.dictionaries[locale] ?? {}; }
export function slotsFor(target: NonNullable<Registration['slots']>[number]['target']) { return registered.flatMap(r => r.slots ?? []).filter(slot => slot.target === target); }
export const gatewayRegistrations = registered.flatMap(r => r.gateway ?? []);
