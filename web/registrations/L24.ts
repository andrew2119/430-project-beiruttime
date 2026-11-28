import manifest from '../../contracts/registrations/L24.json';
import type { Registration } from '../registry-types';

export type LaneModule = {
  id: string;
  registration: Registration;
};

const lanePattern = /^L(?:0[0-9]|1[0-9]|2[0-5])$/;
const services = new Set(['identity', 'catalog', 'auction', 'pricing', 'orders',
  'eligibility', 'trust', 'communications', 'service-operations']);
type Slot = NonNullable<Registration['slots']>[number];
export type SlotDescriptor = Pick<Slot, 'id' | 'target'> & { component: string };
export type SlotComponents = ReadonlyMap<string, Slot['load']>;
const slotTargets = new Set(['watch.detail', 'buyer.dashboard', 'seller.dashboard', 'operator.dashboard']);

const roles = new Set(['public', 'buyer', 'private_seller', 'dealer', 'brand', 'operator']);

function safePath(path: string, versioned = false) {
  return /^\/(?:[a-zA-Z0-9_-]+|:[a-zA-Z][a-zA-Z0-9_]*)(?:\/(?:[a-zA-Z0-9_-]+|:[a-zA-Z][a-zA-Z0-9_]*))*$/.test(path)
    && (!versioned || path.startsWith('/v1/'));
}

function shape(path: string) {
  return path.replace(/:[a-zA-Z][a-zA-Z0-9_]*/g, ':id');
}

function validate(entry: Registration) {
  if (!lanePattern.test(entry.lane) || !/^[a-z][a-z0-9-]*$/.test(entry.namespace)) {
    throw new Error('Invalid lane or namespace');
  }
  if (Object.keys(entry.dictionaries.en).sort().join('|') !== Object.keys(entry.dictionaries.ar).sort().join('|')) {
    throw new Error('Translation keys differ');
  }
  for (const route of entry.routes) {
    if ((route.path !== '/' && !safePath(route.path)) || !route.roles.length || route.roles.some(role => !roles.has(role))) {
      throw new Error('Invalid route or access boundary');
    }
  }
  for (const slot of entry.slots ?? []) {
    if (!/^L[0-9]{2}\.[a-z][a-z0-9.-]*$/.test(slot.id)
      || !slotTargets.has(slot.target) || typeof slot.load !== 'function') throw new Error('Invalid slot boundary');
  }
  for (const endpoint of entry.gateway ?? []) {
    if (!services.has(endpoint.service) || !safePath(endpoint.path, true)
      || !endpoint.methods.length || !endpoint.roles.length
      || endpoint.roles.some(role => !roles.has(role))
      || endpoint.methods.some(method => !['GET', 'POST', 'PATCH', 'PUT', 'DELETE'].includes(method))) {
      throw new Error('Invalid gateway boundary');
    }
    if (endpoint.forwardCookies?.length && endpoint.service !== 'identity') throw new Error('Invalid cookie boundary');
    for (const limit of [endpoint.maxBodyBytes, endpoint.maxResponseBytes]) {
      if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 16 * 1024 * 1024)) {
        throw new Error('Invalid byte budget');
      }
    }
  }
}

/** Build a fresh fragment; missing metadata never exposes a guessed endpoint. */
export function composeL24(modules: readonly LaneModule[], existing: readonly Registration[] = []): Registration {
  const result: Registration = {
    lane: 'L24', namespace: 'lane-registration', routes: [], navigation: [],
    dictionaries: { en: {}, ar: {} }, gateway: [], slots: [],
  };
  const namespaces = new Set<string>([result.namespace]);
  const seen = new Set<string>();
  const claims = new Set<string>();
  function reserve(entry: Registration) {
    validate(entry);
    if (namespaces.has(entry.namespace)) throw new Error('Duplicate namespace');
    namespaces.add(entry.namespace);
    const keys = [
      ...entry.routes.map(route => `route:${shape(route.path)}`),
      ...(entry.navigation ?? []).map(nav => `navigation:${nav.id}`),
      ...(entry.slots ?? []).map(slot => `slot:${slot.id}`),
      ...(entry.gateway ?? []).flatMap(endpoint => endpoint.methods.map(method =>
        `gateway:${endpoint.service}:${method}:${shape(endpoint.path)}`)),
    ];
    for (const key of keys) {
      if (claims.has(key)) throw new Error('Duplicate registration');
      claims.add(key);
    }
  }
  existing.forEach(reserve);
  for (const item of [...modules].sort((a, b) => a.id.localeCompare(b.id))) {
    if (!/^L24\.[a-z][a-z0-9.-]*$/.test(item.id) || item.registration.lane !== 'L24' || seen.has(item.id)) {
      throw new Error('Invalid or duplicate module');
    }
    seen.add(item.id);
    reserve(item.registration);
    const entry = item.registration;
    if (Object.keys(entry.dictionaries.en).length) throw new Error('Module dictionaries require their own namespace');
    result.routes.push(...entry.routes);
    result.navigation!.push(...(entry.navigation ?? []));
    result.gateway!.push(...(entry.gateway ?? []));
    result.slots!.push(...(entry.slots ?? []));
  }
  return result;
}



export type RuntimeModule = LaneModule & {
  service: NonNullable<Registration['gateway']>[number]['service'];
  requires: string[];
  migrations: string[];
  receivers: string[];
  destinations: string[];
};

/** Order complete item migrations before any receiver or destination activation. */
export function planL24(modules: readonly RuntimeModule[], available: readonly string[] = []) {
  composeL24(modules);
  const byId = new Map(modules.map(item => [item.id, item]));
  const complete = new Set(available);
  const visiting = new Set<string>();
  const ordered: RuntimeModule[] = [];
  const migrationKeys = new Set<string>();
  for (const item of modules) {
    if (!services.has(item.service) || complete.has(item.id)) throw new Error('Invalid runtime owner');
    if (item.migrations.join('|') !== [...new Set(item.migrations)].sort().join('|')) {
      throw new Error('Migrations must be unique and ordered');
    }
    for (const migration of item.migrations) {
      if (!/^migrations\/L24_[0-9]{4}_[a-z0-9_]+\.sql$/.test(migration)) throw new Error('Invalid additive migration');
      const key = `${item.service}:${migration}`;
      if (migrationKeys.has(key)) throw new Error('Duplicate migration');
      migrationKeys.add(key);
    }
    if (item.destinations.some(destination => !item.receivers.includes(destination))) {
      throw new Error('Destination requires a subscribed receiver');
    }
  }
  function visit(id: string) {
    if (complete.has(id)) return;
    if (visiting.has(id)) throw new Error('Cyclic module dependency');
    const item = byId.get(id);
    if (!item) throw new Error('Module dependency unavailable');
    visiting.add(id);
    [...item.requires].sort().forEach(visit);
    visiting.delete(id);
    complete.add(id);
    ordered.push(item);
  }
  [...byId.keys()].sort().forEach(visit);
  return {
    migrations: ordered.flatMap(item => item.migrations.map(path => ({ item: item.id, service: item.service, path }))),
    receivers: ordered.flatMap(item => item.receivers.map(event => ({ item: item.id, service: item.service, event }))),
    destinations: ordered.flatMap(item => item.destinations.map(event => ({ item: item.id, service: item.service, event }))),
  };
}

export type DependencyResult<T> =
  | { state: 'ready'; value: T }
  | { state: 'denied' | 'review_required' | 'pending' | 'unavailable'; reason: string };
export type OperationBinding = {
  operation_id: string;
  actor_id: string;
  organization_id: string | null;
  subject_id: string;
  watch_id: string | null;
  expected_revision: number;
  quote_revision: number | null;
  policy_revision: number;
};

type DependencyBudget = { active: number; failures: number; reopenAt: number };

/** Operations share their service budget. The provider owns durable receipts. */
export function createL24Dependency<T>(
  service: NonNullable<Registration['gateway']>[number]['service'],
  invoke: (binding: OperationBinding, signal: AbortSignal) => Promise<DependencyResult<T>>,
  budget: DependencyBudget = { active: 0, failures: 0, reopenAt: 0 },
) {
  if (!services.has(service)) throw new Error('Invalid dependency');
  const inflight = new Map<string, { fingerprint: string; result: Promise<DependencyResult<T>> }>();
  return (binding: OperationBinding): Promise<DependencyResult<T>> => {
    const fingerprint = JSON.stringify([binding.actor_id, binding.organization_id, binding.subject_id,
      binding.watch_id, binding.expected_revision, binding.quote_revision, binding.policy_revision]);
    if (!binding.operation_id || !binding.actor_id || !binding.subject_id
      || !Number.isSafeInteger(binding.expected_revision) || binding.expected_revision < 0
      || !Number.isSafeInteger(binding.policy_revision) || binding.policy_revision < 0) {
      return Promise.resolve({ state: 'denied', reason: 'invalid_binding' });
    }
    const prior = inflight.get(binding.operation_id);
    if (prior) return prior.fingerprint === fingerprint ? prior.result
      : Promise.resolve({ state: 'denied', reason: 'operation_conflict' });
    if (Date.now() < budget.reopenAt) return Promise.resolve({ state: 'pending', reason: 'circuit_open' });
    if (budget.active >= 4) return Promise.resolve({ state: 'pending', reason: 'dependency_busy' });
    const snapshot = { ...binding };
    const result = (async (): Promise<DependencyResult<T>> => {
      budget.active++;
      const controller = new AbortController();
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        const timeout = new Promise<DependencyResult<T>>(resolve => {
          timer = setTimeout(() => {
            resolve({ state: 'pending', reason: 'timeout' });
            controller.abort();
          }, 2000);
        });
        const invocation = Promise.resolve().then(() => invoke(snapshot, controller.signal)).finally(() => {
          budget.active--;
          inflight.delete(snapshot.operation_id);
        });
        const response = await Promise.race([invocation, timeout]);
        if (response.state === 'pending' || response.state === 'unavailable') {
          budget.failures++;
        } else {
          budget.failures = 0;
        }
        if (budget.failures >= 3) budget.reopenAt = Date.now() + 30000;
        return response;
      } catch {
        if (++budget.failures >= 3) budget.reopenAt = Date.now() + 30000;
        return { state: 'pending', reason: 'result_unknown' };
      } finally {
        clearTimeout(timer);
      }
    })();
    inflight.set(snapshot.operation_id, { fingerprint, result });
    return result;
  };
}

export type DiscoveredModule = RuntimeModule & {
  operations: { id: string; path: string; method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE' }[];
};
/** Steps must be idempotent by service and path/event after an uncertain response. */
export type RuntimeBindings = {
  migrate: (item: ReturnType<typeof planL24>['migrations'][number]) => Promise<void>;
  subscribe: (item: ReturnType<typeof planL24>['receivers'][number]) => Promise<void>;
  enable: (item: ReturnType<typeof planL24>['destinations'][number]) => Promise<void>;
  invoke: (service: RuntimeModule['service'], operation: string, binding: OperationBinding,
    signal: AbortSignal) => Promise<DependencyResult<unknown>>;
};

/** Consume the same discovered metadata for registration, planning and dispatch. */
export function createL24Runtime(source: { modules: readonly DiscoveredModule[] },
  bindings?: RuntimeBindings, existing: readonly Registration[] = []) {
  const candidate = composeL24(source.modules, existing);
  const registration = composeL24([]);
  const plan = planL24(source.modules);
  const operations = new Map<string, (binding: OperationBinding) => Promise<DependencyResult<unknown>>>();
  const budgets = new Map<RuntimeModule['service'], DependencyBudget>();
  for (const item of source.modules) {
    if (!budgets.has(item.service)) budgets.set(item.service, { active: 0, failures: 0, reopenAt: 0 });
    for (const operation of item.operations) {
      if (!operation.id || operations.has(operation.id) || !item.registration.gateway?.some(endpoint =>
        endpoint.service === item.service && endpoint.path === operation.path && endpoint.methods.includes(operation.method))) {
        throw new Error('Invalid or duplicate operation lookup');
      }
      operations.set(operation.id, createL24Dependency(item.service, (binding, signal) => bindings
        ? bindings.invoke(item.service, operation.id, binding, signal)
        : Promise.resolve({ state: 'unavailable', reason: 'provider_unavailable' }), budgets.get(item.service)));
    }
  }
  const completed = new Set<unknown>();
  async function apply<T>(items: readonly T[], action: (item: T) => Promise<void>) {
    for (const item of items) {
      if (completed.has(item)) continue;
      await action(item);
      completed.add(item);
    }
  }
  let activated = false;
  let activation: Promise<Registration> | undefined;
  return {
    registration, plan,
    activate(): Promise<Registration> {
      if (activation) return activation;
      if (!bindings) return Promise.reject(new Error('Runtime bindings unavailable'));
      activation = (async () => {
        await apply(plan.migrations, bindings.migrate);
        await apply(plan.receivers, bindings.subscribe);
        await apply(plan.destinations, bindings.enable);
        Object.assign(registration, candidate);
        activated = true;
        return registration;
      })().catch(error => {
        activation = undefined;
        throw error;
      });
      return activation;
    },
    call(operation: string, binding: OperationBinding): Promise<DependencyResult<unknown>> {
      if (!activated) return Promise.resolve({ state: 'unavailable', reason: 'runtime_inactive' });
      const invoke = operations.get(operation);
      return invoke ? invoke(binding) : Promise.resolve({ state: 'unavailable', reason: 'operation_unavailable' });
    },
  };
}

/** Validate serialized metadata before composing any public declarations. */
export function decodeL24Modules(value: unknown, components: SlotComponents = new Map()): DiscoveredModule[] {
  if (!Array.isArray(value)) throw new Error('Invalid module metadata');
  const strings = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === 'string');
  for (const item of value) {
    if (!item || typeof item !== 'object' || typeof item.id !== 'string'
      || typeof item.service !== 'string' || !strings(item.requires) || !strings(item.migrations)
      || !strings(item.receivers) || !strings(item.destinations) || !Array.isArray(item.operations)) {
      throw new Error('Invalid module metadata');
    }
    const entry = item.registration;
    if (!entry || typeof entry.lane !== 'string' || typeof entry.namespace !== 'string'
      || !Array.isArray(entry.routes) || !entry.dictionaries?.en || !entry.dictionaries?.ar
      || (entry.slots !== undefined && !Array.isArray(entry.slots))) {
      throw new Error('Invalid serialized registration');
    }
    for (const route of entry.routes) {
      if (!route || typeof route.path !== 'string' || !strings(route.roles)
        || !['storefront', 'account', 'seller', 'operator'].includes(route.area)) throw new Error('Invalid serialized route');
    }
    if (entry.gateway !== undefined && !Array.isArray(entry.gateway)) throw new Error('Invalid serialized gateway');
    for (const endpoint of entry.gateway ?? []) {
      if (!endpoint || typeof endpoint.path !== 'string' || !strings(endpoint.methods) || !strings(endpoint.roles)) {
        throw new Error('Invalid serialized gateway');
      }
    }
    for (const operation of item.operations) {
      if (!operation || typeof operation.id !== 'string' || typeof operation.path !== 'string'
        || !['GET', 'POST', 'PATCH', 'PUT', 'DELETE'].includes(operation.method)) throw new Error('Invalid serialized operation');
    }
  }
  const modules = value.map(item => ({
    ...item,
    registration: {
      ...item.registration,
      slots: (item.registration.slots ?? []).map((slot: SlotDescriptor) => {
        if (!slot || typeof slot.id !== 'string' || !/^L24\.[a-z][a-z0-9.-]*$/.test(slot.id)
          || !slotTargets.has(slot.target) || typeof slot.component !== 'string'
          || !/^L24\.[a-z][a-z0-9.-]*$/.test(slot.component)
          || Object.keys(slot).some(key => !['id', 'target', 'component'].includes(key))) {
          throw new Error('Invalid serialized slot');
        }
        const load = components.get(slot.component);
        if (typeof load !== 'function') throw new Error('Slot component unavailable');
        return { id: slot.id, target: slot.target, load };
      }),
    },
  })) as DiscoveredModule[];
  planL24(modules);
  return modules;
}

export const runtimeL24 = createL24Runtime({ modules: decodeL24Modules(manifest.composition.modules) });
export default runtimeL24.registration;
