import manifest from '../../contracts/registrations/L25.json';
import type { Registration } from '../registry-types';
import type { ServiceName } from '../lib/api/types';

const lanePattern = /^L(0[0-9]|1[0-9]|2[0-5])$/;
const services: readonly ServiceName[] = ['identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility', 'trust', 'communications', 'service-operations'];
const roles = new Set(['public', 'buyer', 'private_seller', 'dealer', 'brand', 'operator']);
const methods = new Set(['GET', 'POST', 'PATCH', 'PUT', 'DELETE']);
const areas = new Set(['storefront', 'account', 'seller', 'operator']);
const targets = new Set(['watch.detail', 'buyer.dashboard', 'seller.dashboard', 'operator.dashboard']);
const pathPattern = /^\/(?:[a-zA-Z0-9_-]+|:[a-zA-Z][a-zA-Z0-9_]*)(?:\/(?:[a-zA-Z0-9_-]+|:[a-zA-Z][a-zA-Z0-9_]*))*$/;
const canonicalPath = (path: string) => path.replace(/:[a-zA-Z][a-zA-Z0-9_]*/g, ':id');

function unique(values: Set<string>, value: string) {
  if (values.has(value)) throw new Error('Duplicate registration');
  values.add(value);
}
function checkRoles(values: string[]) {
  if (!values.length || new Set(values).size !== values.length || values.some(value => !roles.has(value))) throw new Error('Invalid access roles');
}

/** Build a fresh snapshot; absent fragments never create routes or permissions. */
export function composeRegistrations(fragments: readonly (Registration | undefined)[], existing: readonly Registration[] = []): Registration[] {
  const namespaces = new Set<string>(), lanes = new Set<string>(), paths = new Set<string>();
  const navigation = new Set<string>(), slots = new Set<string>(), endpoints = new Set<string>();
  const preserved = new Set(existing);
  const entries = [...existing, ...fragments.filter((entry): entry is Registration => entry !== undefined)];
  for (const entry of entries) {
    if (!lanePattern.test(entry.lane) || !/^[a-z][a-z0-9-]*$/.test(entry.namespace)) throw new Error('Invalid lane or namespace');
    unique(lanes, entry.lane);
    unique(namespaces, entry.namespace);
    if (Object.keys(entry.dictionaries.en).sort().join('|') !== Object.keys(entry.dictionaries.ar).sort().join('|')) throw new Error('Translation keys differ');
    for (const route of entry.routes) {
      if ((route.path !== '/' && !pathPattern.test(route.path)) || !areas.has(route.area)) throw new Error('Invalid route');
      checkRoles(route.roles);
      unique(paths, canonicalPath(route.path));
    }
    for (const item of entry.navigation ?? []) {
      unique(navigation, item.id);
      checkRoles(item.roles);
      if (!entry.routes.some(route => route.path === (item.href || '/') && item.roles.every(role => route.roles.includes(role)))) throw new Error('Navigation requires an owned route');
      if (!item.label.en || !item.label.ar || !Number.isFinite(item.order)) throw new Error('Invalid navigation');
    }
    for (const slot of entry.slots ?? []) {
      if (!targets.has(slot.target) || typeof slot.load !== 'function') throw new Error('Invalid slot');
      unique(slots, slot.id);
    }
    for (const endpoint of entry.gateway ?? []) {
      if (!services.includes(endpoint.service) || !pathPattern.test(endpoint.path) || !endpoint.path.startsWith('/v1/')) throw new Error('Invalid gateway path or service');
      checkRoles(endpoint.roles);
      if (!endpoint.methods.length) throw new Error('Missing gateway method');
      for (const method of endpoint.methods) {
        if (!methods.has(method)) throw new Error('Invalid gateway method');
        const key = `${endpoint.service}:${method}:${canonicalPath(endpoint.path)}`;
        if (!preserved.has(entry)) unique(endpoints, key);
        else endpoints.add(key);
      }
      for (const budget of [endpoint.maxBodyBytes, endpoint.maxResponseBytes]) {
        if (budget !== undefined && (!Number.isSafeInteger(budget) || budget < 1 || budget > 16 * 1024 * 1024)) throw new Error('Invalid byte budget');
      }
    }
  }
  const emitted = new Set<string>();
  return entries.map(entry => ({ ...entry, gateway: entry.gateway?.flatMap(endpoint => {
    const kept = endpoint.methods.filter(method => {
      const key = `${endpoint.service}:${method}:${canonicalPath(endpoint.path)}`;
      if (emitted.has(key)) return false;
      emitted.add(key);
      return true;
    });
    return kept.length ? [{ ...endpoint, methods: kept }] : [];
  }) }));
}

export type RuntimeModule = {
  id: string;
  service: ServiceName;
  migrations: string[];
  requires: string[];
  receives: string[];
  destinations: { event: string; receiver: string }[];
};

/** Validate the entire additive plan before any receiver or destination is enabled. */
export function runtimePlan(modules: readonly RuntimeModule[]) {
  const byId = new Map<string, RuntimeModule>(), migrations = new Set<string>();
  for (const entry of modules) {
    const [lane] = entry.id.split('.');
    if (!lanePattern.test(lane) || !/^L\d{2}\.[a-z][a-z0-9.-]*$/.test(entry.id) || !services.includes(entry.service)) throw new Error('Invalid runtime entry');
    if (byId.has(entry.id)) throw new Error('Duplicate runtime entry');
    byId.set(entry.id, entry);
    if (entry.migrations.join('|') !== [...entry.migrations].sort().join('|')) throw new Error('Unordered migrations');
    for (const migration of entry.migrations) {
      if (!new RegExp(`^${lane}_[0-9]{4}_[a-z0-9_]+\\.sql$`).test(migration)) throw new Error('Invalid additive migration');
      unique(migrations, `${entry.service}:${migration}`);
    }
  }
  const ordered: RuntimeModule[] = [], visiting = new Set<string>(), visited = new Set<string>();
  function visit(id: string) {
    if (visited.has(id)) return;
    const entry = byId.get(id);
    if (!entry || visiting.has(id)) throw new Error('Missing or cyclic entry dependency');
    visiting.add(id);
    for (const dependency of [...entry.requires].sort()) {
      if (byId.get(dependency)?.service !== entry.service) throw new Error('Migration dependencies must be service-local');
      visit(dependency);
    }
    visiting.delete(id);
    visited.add(id);
    ordered.push(entry);
  }
  for (const id of [...byId.keys()].sort()) visit(id);
  const receivers = new Set<string>(), destinations = new Set<string>();
  for (const entry of ordered) for (const event of entry.receives) unique(receivers, `${entry.id}:${event}`);
  for (const entry of ordered) for (const destination of entry.destinations) {
    if (!receivers.has(`${destination.receiver}:${destination.event}`)) throw new Error('Destination requires a subscribed receiver');
    unique(destinations, `${entry.id}:${destination.receiver}:${destination.event}`);
  }
  return { modules: ordered, receivers: [...receivers].sort(), destinations: [...destinations].sort(), phases: ['migrate', 'subscribe', 'enable'] as const };
}

export type OutcomeModule = RuntimeModule & {
  outcome: string;
  routes: Registration['routes'];
  slots: NonNullable<Registration['slots']>;
  operations: (NonNullable<Registration['gateway']>[number] & { operation_id: string })[];
  connection: 'deferred' | 'connected';
};

/** The default export is consumed by registration discovery without a second index. */
export function registrationFromModules(modules: readonly OutcomeModule[]): Registration {
  runtimePlan(modules);
  const operations = new Set<string>();
  for (const outcome of modules) for (const operation of outcome.operations) {
    unique(operations, operation.operation_id);
    if (operation.service !== outcome.service) throw new Error('Operation service differs');
  }
  const registration: Registration = {
    lane: 'L25', namespace: 'lane-composition',
    routes: modules.flatMap(outcome => outcome.routes),
    navigation: [], dictionaries: { en: {}, ar: {} },
    slots: modules.flatMap(outcome => outcome.slots),
    gateway: modules.flatMap(outcome => outcome.operations.map(({ operation_id, ...endpoint }) => {
      if (!/^l25\.[a-z0-9.-]+\.v[1-9][0-9]*$/.test(operation_id)) throw new Error('Invalid operation lookup');
      return endpoint;
    })),
  };
  return composeRegistrations([registration])[0];
}

export const outcomeModules: OutcomeModule[] = manifest.modules.map(outcome => ({
  ...outcome,
  service: outcome.service as ServiceName,
  connection: outcome.connection as OutcomeModule['connection'],
  operations: outcome.operations.map(operation => ({
    operation_id: operation.operation_id,
    service: outcome.service as ServiceName, path: operation.path,
    methods: [operation.method as 'GET'], roles: operation.roles as Registration['routes'][number]['roles'],
    maxResponseBytes: operation.maxResponseBytes,
  })),
}));

export default registrationFromModules(outcomeModules);

const outcomeGates = new Map<ServiceName, DependencyGate>();

/** Missing producers remain unavailable; deterministic fixtures never authorize a read. */
export async function readOutcome(
  operationId: string,
  invoke?: (outcome: OutcomeModule, operationId: string, signal: AbortSignal) => Promise<DependencyResult<unknown>>,
): Promise<DependencyResult<unknown>> {
  const outcome = outcomeModules.find(item => item.operations.some(operation => operation.operation_id === operationId));
  if (!outcome) return { state: 'denied' };
  if (!invoke) return { state: 'unavailable' };
  let gate = outcomeGates.get(outcome.service);
  if (!gate) { gate = new DependencyGate(); outcomeGates.set(outcome.service, gate); }
  return gate.call(signal => invoke(outcome, operationId, signal), Date.now() + 4000);
}

export type DependencyResult<T> =
  | { state: 'current'; value: T }
  | { state: 'denied' | 'stale' | 'pending' | 'unavailable' };

/** One instance per dependency; uncertain commands retain their caller's reference. */
export class DependencyGate {
  private failures = 0;
  private openUntil = 0;
  private busy = false;
  constructor(private readonly now: () => number = Date.now) {}

  async call<T>(operation: (signal: AbortSignal) => Promise<DependencyResult<T>>, deadline: number): Promise<DependencyResult<T>> {
    const remaining = Math.min(1500, deadline - this.now());
    if (!Number.isFinite(remaining) || remaining <= 0 || this.busy || this.openUntil > this.now()) return { state: 'unavailable' };
    this.busy = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let timedOut = false;
    const timeout = new Promise<DependencyResult<T>>(resolve => {
      timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
        resolve({ state: 'pending' });
      }, remaining);
    });
    // Keep the concurrency slot until the underlying call settles, even after abort.
    const request = Promise.resolve().then(() => operation(controller.signal)).finally(() => { this.busy = false; });
    try {
      const result = await Promise.race([request, timeout]);
      if (timedOut || result.state === 'unavailable' || result.state === 'pending') this.failed();
      else { this.failures = 0; this.openUntil = 0; }
      return result;
    } catch {
      this.failed();
      return { state: 'pending' };
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
  private failed() {
    if (++this.failures >= 3) this.openUntil = this.now() + 30000;
  }
}

export type CompositionAdapter = {
  migrate: (entry: RuntimeModule, operationId: string, signal: AbortSignal) => Promise<DependencyResult<unknown>>;
  subscribe: (entry: RuntimeModule, event: string, operationId: string, signal: AbortSignal) => Promise<DependencyResult<unknown>>;
  enable: (entry: RuntimeModule, destination: RuntimeModule['destinations'][number], operationId: string, signal: AbortSignal) => Promise<DependencyResult<unknown>>;
};

/** Retain one instance and the same reference while settling an activation. */
export class CompositionRuntime {
  private readonly gates = new Map<ServiceName, DependencyGate>();
  private readonly receipts = new Set<string>();
  private operationId: string | undefined;
  private snapshot: string | undefined;

  constructor(private readonly adapter: CompositionAdapter, private readonly now: () => number = Date.now) {}

  async activate(
    fragments: readonly (Registration | undefined)[],
    modules: readonly RuntimeModule[],
    operationId: string,
    existing: readonly Registration[] = [],
    deadline: number = this.now() + 4000,
  ): Promise<DependencyResult<Registration[]>> {
    const registrations = composeRegistrations(fragments, existing);
    const plan = runtimePlan(modules);
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(operationId)) throw new Error('Invalid operation reference');
    const snapshot = JSON.stringify({ registrations, modules: plan.modules });
    if (this.operationId !== undefined && (this.operationId !== operationId || this.snapshot !== snapshot)) return { state: 'stale' };
    this.operationId = operationId;
    this.snapshot = snapshot;
    const steps: { service: ServiceName; key: string; run: (signal: AbortSignal) => Promise<DependencyResult<unknown>> }[] = [];
    for (const entry of plan.modules) steps.push({ service: entry.service, key: `migrate:${entry.id}`, run: signal => this.adapter.migrate(entry, operationId, signal) });
    for (const entry of plan.modules) for (const event of entry.receives) steps.push({ service: entry.service, key: `subscribe:${entry.id}:${event}`, run: signal => this.adapter.subscribe(entry, event, operationId, signal) });
    for (const entry of plan.modules) for (const destination of entry.destinations) steps.push({ service: entry.service, key: `enable:${entry.id}:${destination.receiver}:${destination.event}`, run: signal => this.adapter.enable(entry, destination, operationId, signal) });
    for (const step of steps) {
      if (this.receipts.has(step.key)) continue;
      let gate = this.gates.get(step.service);
      if (!gate) { gate = new DependencyGate(this.now); this.gates.set(step.service, gate); }
      const result = await gate.call(step.run, deadline);
      if (result.state !== 'current') return result;
      this.receipts.add(step.key);
    }
    return { state: 'current', value: registrations };
  }
}


export type CompositionCommand = {
  schema_version: 'lane-composition.v1';
  operation_id: string;
  step_id: string;
  module: RuntimeModule;
  event: string | null;
  destination: RuntimeModule['destinations'][number] | null;
};

/** The host supplies authenticated service-local delivery, never browser credentials. */
export type CompositionTransport = (
  service: ServiceName,
  path: string,
  command: CompositionCommand,
  signal: AbortSignal,
) => Promise<unknown>;

function compositionAdapter(deliver: CompositionTransport): CompositionAdapter {
  async function send(phase: 'migrate' | 'subscribe' | 'enable', entry: RuntimeModule, reference: string, signal: AbortSignal, event: string | null = null, destination: RuntimeModule['destinations'][number] | null = null): Promise<DependencyResult<unknown>> {
    const stepId = `${phase}:${entry.id}${destination ? `:${destination.receiver}:${destination.event}` : event ? `:${event}` : ''}`;
    const response = await deliver(entry.service, `/internal/v1/lane-composition/${phase}`, {
      schema_version: 'lane-composition.v1', operation_id: reference, step_id: stepId,
      module: entry, event, destination,
    }, signal);
    if (!response || typeof response !== 'object' || !('state' in response)) return { state: 'pending' };
    const state = response.state;
    if (state === 'current') {
      if (!('operation_id' in response) || response.operation_id !== reference || !('step_id' in response) || response.step_id !== stepId) return { state: 'pending' };
      return { state, value: null };
    }
    if (state === 'denied' || state === 'stale' || state === 'pending' || state === 'unavailable') return { state };
    return { state: 'pending' };
  }
  return {
    migrate: (entry, reference, signal) => send('migrate', entry, reference, signal),
    subscribe: (entry, event, reference, signal) => send('subscribe', entry, reference, signal, event),
    enable: (entry, destination, reference, signal) => send('enable', entry, reference, signal, null, destination),
  };
}

/** Executable host boundary: discovery completes before any service-local command. */
export function createCompositionBoundary(
  discover: (signal: AbortSignal) => Promise<{ fragments: (Registration | undefined)[]; modules: RuntimeModule[]; existing: Registration[] }>,
  deliver: CompositionTransport,
  now: () => number = Date.now,
) {
  const runtime = new CompositionRuntime(compositionAdapter(deliver), now);
  const discoveryGate = new DependencyGate(now);
  let reference: string | undefined;
  return async (operationId: string): Promise<DependencyResult<Registration[]>> => {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(operationId)) throw new Error('Invalid operation reference');
    if (reference !== undefined && reference !== operationId) return { state: 'stale' };
    reference = operationId;
    const deadline = now() + 4000;
    const discovery = await discoveryGate.call(async signal => ({ state: 'current', value: await discover(signal) }), deadline);
    if (discovery.state !== 'current') return discovery;
    const metadata = discovery.value;
    return runtime.activate(metadata.fragments, metadata.modules, operationId, metadata.existing, deadline);
  };
}

/** Service-local hosts use the same discovered metadata as the public registration. */
export function createLaneBoundary(deliver: CompositionTransport, now: () => number = Date.now) {
  return createCompositionBoundary(async () => ({
    fragments: [registrationFromModules(outcomeModules)], modules: outcomeModules, existing: [],
  }), deliver, now);
}
