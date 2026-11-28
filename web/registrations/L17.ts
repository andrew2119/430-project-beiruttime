import type { Registration } from '../registry-types';

type Gateway = NonNullable<Registration['gateway']>[number];
export type L17Module = {
  outcome: 'C08' | 'S01' | 'S05' | 'S11';
  id: string;
  registration: Registration;
  migrations: string[];
  requires: string[];
  receivers: string[];
  destinations: string[];
};

const outcomes = new Set(['C08', 'S01', 'S05', 'S11']);
const services = new Set(['identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility', 'trust', 'communications', 'service-operations']);
const roles = new Set(['public', 'buyer', 'private_seller', 'dealer', 'brand', 'operator']);
const methods = new Set(['GET', 'POST', 'PATCH', 'PUT', 'DELETE']);
const empty = (): Registration => ({
  lane: 'L17', namespace: 'l17-workflows', routes: [], navigation: [],
  dictionaries: { en: {}, ar: {} }, gateway: [], slots: [],
});
function pathsOverlap(left: string, right: string) {
  const a = left.split('/'), b = right.split('/');
  return a.length === b.length && a.every((part, index) => part === b[index] || part.startsWith(':') || b[index].startsWith(':'));
}
function addPath(paths: string[], path: string) {
  if (paths.some(existing => pathsOverlap(existing, path))) throw new Error('Duplicate or overlapping registration');
  paths.push(path);
}
function validPath(path: string) {
  return /^\/(?:[a-z0-9-]+|:[a-z][a-z0-9_]*)(?:\/(?:[a-z0-9-]+|:[a-z][a-z0-9_]*))*$/.test(path);
}
function unique(keys: Set<string>, key: string) {
  if (keys.has(key)) throw new Error('Duplicate registration');
  keys.add(key);
}
function validRoles(values: string[]) {
  if (!values.length || values.some(role => !roles.has(role))) throw new Error('Invalid access roles');
}
function validateGateway(endpoint: Gateway) {
  if (!services.has(endpoint.service) || !validPath(endpoint.path) || !endpoint.path.startsWith('/v1/')) throw new Error('Invalid service path');
  validRoles(endpoint.roles);
  if (!endpoint.methods.length || endpoint.methods.some(method => !methods.has(method))) throw new Error('Invalid methods');
  if (endpoint.roles.includes('public') || endpoint.forwardCookies?.length) throw new Error('Private operations require current access');
  for (const limit of [endpoint.maxBodyBytes, endpoint.maxResponseBytes]) {
    if (!Number.isInteger(limit) || limit! < 1 || limit! > 16 * 1024 * 1024) throw new Error('Explicit byte bounds required');
  }
}

// Missing leaves expose no commands. Current access remains the destination's responsibility.
export function composeL17(modules: readonly L17Module[] = [], existing: readonly Registration[] = []): Registration {
  const result = empty();
  if (existing.some(entry => entry.namespace === result.namespace || entry.lane === result.lane)) throw new Error('Duplicate lane or namespace');
  const paths = existing.flatMap(entry => entry.routes.map(route => route.path));
  const gateways = existing.flatMap(entry => (entry.gateway ?? []).flatMap(endpoint => endpoint.methods.map(method => ({ service: endpoint.service, method, path: endpoint.path }))));
  const slots = new Set(existing.flatMap(entry => (entry.slots ?? []).map(slot => slot.id)));
  const navigation = new Set(existing.flatMap(entry => (entry.navigation ?? []).map(item => item.id)));
  const seen = new Set<string>();
  for (const fragment of [...modules].sort((a, b) => a.id.localeCompare(b.id))) {
    if (!outcomes.has(fragment.outcome) || !/^L17\.[a-z][a-z0-9-]*$/.test(fragment.id)) throw new Error('Invalid fragment');
    unique(seen, fragment.id);
    const entry = fragment.registration;
    if (entry.lane !== 'L17' || !/^l17-[a-z][a-z0-9-]*$/.test(entry.namespace)) throw new Error('Invalid namespace');
    unique(seen, entry.namespace);
    if (Object.keys(entry.dictionaries.en).sort().join('|') !== Object.keys(entry.dictionaries.ar).sort().join('|')) throw new Error('Translation keys differ');
    for (const locale of ['en', 'ar'] as const) {
      for (const [key, value] of Object.entries(entry.dictionaries[locale])) {
        const name = `${entry.namespace}_${key}`;
        if (!value.trim()) throw new Error('Missing translation');
        result.dictionaries[locale][name] = value;
      }
    }
    for (const route of entry.routes) {
      if (!validPath(route.path)) throw new Error('Invalid route');
      validRoles(route.roles);
      if (route.roles.includes('public')) throw new Error('Private route required');
      addPath(paths, route.path);
      result.routes.push({ ...route, roles: [...route.roles] });
    }
    for (const endpoint of entry.gateway ?? []) {
      validateGateway(endpoint);
      for (const method of endpoint.methods) {
        if (gateways.some(other => other.service === endpoint.service && other.method === method && pathsOverlap(other.path, endpoint.path))) throw new Error('Duplicate or overlapping registration');
        gateways.push({ service: endpoint.service, method, path: endpoint.path });
      }
      result.gateway!.push({ ...endpoint, roles: [...endpoint.roles], methods: [...endpoint.methods] });
    }
    for (const item of entry.navigation ?? []) {
      if (!item.id.startsWith('l17-') || !entry.routes.some(route => route.path === item.href && route.area === item.area && item.roles.every(role => route.roles.includes(role)))) throw new Error('Navigation requires a matching route');
      validRoles(item.roles);
      if (!item.label.en.trim() || !item.label.ar.trim()) throw new Error('Missing navigation translation');
      unique(navigation, item.id);
      result.navigation!.push({ ...item, roles: [...item.roles], label: { ...item.label } });
    }
    for (const slot of entry.slots ?? []) {
      if (!slot.id.startsWith('l17-')) throw new Error('Invalid slot');
      unique(slots, slot.id);
      result.slots!.push({ ...slot });
    }
  }
  planL17(modules);
  return result;
}

// The runtime applies the complete additive plan before subscribing and enabling delivery.
export function planL17(modules: readonly L17Module[]) {
  const ordered: L17Module[] = [];
  const remaining = new Map(modules.map(fragment => [fragment.id, fragment]));
  if (remaining.size !== modules.length) throw new Error('Duplicate fragment');
  const done = new Set<string>();
  const migrations = new Set<string>();
  while (remaining.size) {
    const ready = [...remaining.values()].filter(fragment => fragment.requires.every(id => done.has(id))).sort((a, b) => a.id.localeCompare(b.id));
    if (!ready.length) throw new Error('Missing or cyclic migration dependency');
    for (const fragment of ready) {
      for (const migration of fragment.migrations) {
        if (!/^migrations\/L17_[0-9]{4}_[a-z0-9_]+\.sql$/.test(migration)) throw new Error('Invalid additive migration');
        unique(migrations, `${fragment.id}:${migration}`);
      }
      ordered.push(fragment); done.add(fragment.id); remaining.delete(fragment.id);
    }
  }
  const receivers = [...new Set(ordered.flatMap(fragment => fragment.receivers))].sort();
  const destinations = [...new Set(ordered.flatMap(fragment => fragment.destinations))].sort();
  if (destinations.some(destination => !receivers.includes(destination))) throw new Error('Destination requires a subscribed receiver');
  return { modules: ordered.map(fragment => fragment.id), migrations: ordered.flatMap(fragment => fragment.migrations.map(path => ({ module: fragment.id, path }))), receivers, destinations };
}

export type L17Discovery = {
  keys(): string[];
  (path: string): { default: L17Module };
};

type RegistrationDiscovery = {
  keys(): string[];
  (path: string): { default: Registration };
};

declare const require: {
  context(path: '../features', recursive: boolean, match: RegExp): L17Discovery;
  context(path: '.', recursive: boolean, match: RegExp): RegistrationDiscovery;
};

const maintenance: L17Module = {
  outcome: 'S01', id: 'L17.maintenance-requests',
  registration: {
    lane: 'L17', namespace: 'l17-maintenance', routes: [], dictionaries: {en: {}, ar: {}},
    gateway: [
      {service: 'service-operations', path: '/v1/maintenance/context/:watch_id', methods: ['GET'], roles: ['buyer'], maxBodyBytes: 4096, maxResponseBytes: 131072},
      {service: 'service-operations', path: '/v1/maintenance/requests', methods: ['POST'], roles: ['buyer'], maxBodyBytes: 16384, maxResponseBytes: 16384},
      {service: 'service-operations', path: '/v1/maintenance/operations/:operation_id', methods: ['GET', 'DELETE'], roles: ['buyer'], maxBodyBytes: 4096, maxResponseBytes: 16384},
      {service: 'service-operations', path: '/v1/maintenance/photos', methods: ['POST'], roles: ['buyer'], maxBodyBytes: 524288, maxResponseBytes: 16384},
      {service: 'service-operations', path: '/v1/maintenance/assessment-inbox', methods: ['GET'], roles: ['brand', 'dealer'], maxBodyBytes: 4096, maxResponseBytes: 32768},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id', methods: ['GET'], roles: ['brand', 'dealer'], maxBodyBytes: 4096, maxResponseBytes: 32768},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/photos/:photo_ref', methods: ['GET'], roles: ['brand', 'dealer'], maxBodyBytes: 4096, maxResponseBytes: 524288},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/assignment', methods: ['GET', 'POST'], roles: ['brand', 'dealer'], maxBodyBytes: 8192, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/watch-confirmation', methods: ['POST'], roles: ['brand', 'dealer'], maxBodyBytes: 8192, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/staff-operations/:operation_id', methods: ['GET'], roles: ['brand', 'dealer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/disposition', methods: ['GET'], roles: ['buyer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/opening-consent', methods: ['GET','POST'], roles: ['buyer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/opening-consent/operations/:operation_id', methods: ['GET','DELETE'], roles: ['buyer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/opening-consent/intake/:order_id', methods: ['GET'], roles: ['brand','dealer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/opening-consent/intake', methods: ['POST'], roles: ['brand','dealer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
      {service: 'service-operations', path: '/v1/maintenance/requests/:request_id/opening-consent/intake/operations/:operation_id', methods: ['GET','DELETE'], roles: ['brand','dealer'], maxBodyBytes: 4096, maxResponseBytes: 8192},
    ],
  },
  migrations: [], requires: [], receivers: [], destinations: [],
};

// Only explicit lane metadata participates; ordinary feature files are never executed.
export function discoverL17(source: L17Discovery): L17Module[] {
  return source.keys().sort().map(path => {
    if (!/^\.\/(?:[a-z0-9-]+\/)+L17\.registration\.ts$/.test(path)) throw new Error('Invalid metadata path');
    return source(path).default;
  });
}

export type L17Runtime = {
  migrate(module: string, path: string): Promise<void>;
  subscribe(receiver: string): Promise<void>;
  enable(destination: string): Promise<void>;
};

// Each invocation belongs to the existing service's serialized startup boundary.
export async function applyL17(runtime: L17Runtime, modules: readonly L17Module[], existing: readonly Registration[]) {
  if (!Array.isArray(existing)) throw new Error('Existing registrations required');
  const registration = composeL17(modules, existing);
  const plan = planL17(modules);
  for (const migration of plan.migrations) await runtime.migrate(migration.module, migration.path);
  for (const receiver of plan.receivers) await runtime.subscribe(receiver);
  for (const destination of plan.destinations) await runtime.enable(destination);
  return registration;
}

// Read sibling registrations directly to avoid a cycle through the generated index.
export function composeDiscoveredL17(source: L17Discovery, siblings: RegistrationDiscovery) {
  const existing = siblings.keys().sort().map(path => {
    if (!/^\.\/L(?:0[0-9]|1[0-6]|1[89]|2[0-5])\.ts$/.test(path)) throw new Error('Invalid sibling registration path');
    return siblings(path).default;
  });
  return composeL17([maintenance, ...discoverL17(source)], existing);
}

export default typeof require !== 'undefined' && typeof require.context === 'function' ? composeDiscoveredL17(
  require.context('../features', true, /\/L17\.registration\.ts$/),
  require.context('.', false, /\/L(?:0[0-9]|1[0-6]|1[89]|2[0-5])\.ts$/),
) : composeL17([maintenance]);
