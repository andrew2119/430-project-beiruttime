import type { Registration } from '../registry-types';

export const lanePattern = /^L(?:0\d|1\d|2[0-5])$/;
export type Fragment = {
  outcome: 'C14' | 'S04';
  registration: Registration;
  migrations: { id: string; after: string[] }[];
  receivers: string[];
  destinations: string[];
};

const empty = (): Registration => ({
  lane: 'L21', namespace: 'job-outcomes', routes: [], navigation: [],
  dictionaries: { en: {}, ar: {} }, gateway: [], slots: [],
});

/** Validate the whole candidate before exposing any registration. */
export function composeOutcomes(
  fragments: readonly Fragment[], existing: readonly Registration[] = [],
  subscribed: ReadonlySet<string> = new Set(),
): { registration: Registration; migrationOrder: string[] } {
  const registration = empty();
  const outcomes = new Set<string>();
  const keys = new Set<string>();
  const migrations = new Map<string, string[]>();
  function claim(key: string) {
    if (keys.has(key)) throw new Error('Duplicate registration');
    keys.add(key);
  }
  function inventory(item: Registration, retained = false) {
    const reserve = retained ? (key: string) => { keys.add(key); } : claim;
    if (!lanePattern.test(item.lane)) throw new Error('Invalid lane');
    reserve(`namespace:${item.namespace}`);
    for (const route of item.routes) reserve(`route:${normalize(route.path)}`);
    for (const route of item.gateway ?? []) {
      for (const method of route.methods) reserve(`gateway:${route.service}:${method}:${normalize(route.path)}`);
    }
    for (const slot of item.slots ?? []) reserve(`slot:${slot.id}`);
    for (const entry of item.navigation ?? []) reserve(`navigation:${entry.id}`);
  }
  for (const item of existing) inventory(item, true);
  claim(`namespace:${registration.namespace}`);
  for (const fragment of fragments) {
    if (!['C14', 'S04'].includes(fragment.outcome) || outcomes.has(fragment.outcome)) throw new Error('Invalid outcome');
    outcomes.add(fragment.outcome);
    if (fragment.registration.lane !== 'L21') throw new Error('Invalid owner');
    inventory(fragment.registration);
    for (const route of fragment.registration.routes) {
      if (!route.roles.length || route.roles.includes('public')) throw new Error('Invalid private route');
    }
    const dictionary = fragment.registration.dictionaries;
    if (JSON.stringify(Object.keys(dictionary.en).sort()) !== JSON.stringify(Object.keys(dictionary.ar).sort())) throw new Error('Incomplete translations');
    for (const destination of fragment.destinations) {
      if (!fragment.receivers.includes(destination) || !subscribed.has(destination)) throw new Error('Receiver pending');
    }
    for (const endpoint of fragment.registration.gateway ?? []) {
      if (endpoint.service !== 'service-operations' || !/^\/v[1-9]\d*\//.test(endpoint.path)
        || endpoint.roles.length === 0 || endpoint.roles.includes('public')
        || endpoint.forwardCookies?.length) throw new Error('Invalid private endpoint');
      for (const bound of [endpoint.maxBodyBytes, endpoint.maxResponseBytes]) {
        if (bound !== undefined && (!Number.isSafeInteger(bound) || bound < 1 || bound > 1048576)) throw new Error('Invalid endpoint bound');
      }
    }
    for (const migration of fragment.migrations) {
      if (!/^L21_[0-9]{4}_[a-z0-9_]+$/.test(migration.id) || migrations.has(migration.id)) throw new Error('Invalid migration');
      migrations.set(migration.id, [...migration.after]);
    }
    registration.routes.push(...fragment.registration.routes);
    registration.navigation!.push(...fragment.registration.navigation ?? []);
    registration.gateway!.push(...fragment.registration.gateway ?? []);
    registration.slots!.push(...fragment.registration.slots ?? []);
    for (const locale of ['en', 'ar'] as const) {
      for (const [key, value] of Object.entries(fragment.registration.dictionaries[locale])) {
        if (Object.hasOwn(registration.dictionaries[locale], key)) throw new Error('Duplicate dictionary key');
        registration.dictionaries[locale][key] = value;
      }
    }
  }
  const migrationOrder: string[] = [];
  const visiting = new Set<string>();
  const visited = new Set<string>();
  function visit(id: string) {
    if (visited.has(id)) return;
    if (visiting.has(id) || !migrations.has(id)) throw new Error('Unresolved migration dependency');
    visiting.add(id);
    for (const dependency of [...migrations.get(id)!].sort()) visit(dependency);
    visiting.delete(id);
    visited.add(id);
    migrationOrder.push(id);
  }
  for (const id of [...migrations.keys()].sort()) visit(id);
  return { registration, migrationOrder };
}

function normalize(path: string): string {
  if (path === '/') return path;
  if (!/^\/(?:[a-zA-Z0-9_-]+|:[a-zA-Z][a-zA-Z0-9_]*)(?:\/(?:[a-zA-Z0-9_-]+|:[a-zA-Z][a-zA-Z0-9_]*))*$/.test(path)) throw new Error('Invalid registration path');
  return path.replace(/:[a-zA-Z][a-zA-Z0-9_]*/g, ':parameter');
}

// Missing outcome metadata exposes no route or destination.
export const operations = {
  'customization.status.v1': { outcome: 'C14', method: 'GET', path: '/v1/job-outcomes/customization/:id' },
  'customization.reconcile.v1': { outcome: 'C14', method: 'POST', path: '/v1/job-outcomes/customization/:id/reconcile' },
  'servicing.status.v1': { outcome: 'S04', method: 'GET', path: '/v1/job-outcomes/servicing/:id' },
  'servicing.reconcile.v1': { outcome: 'S04', method: 'POST', path: '/v1/job-outcomes/servicing/:id/reconcile' },
} as const;

const boundedGateway: NonNullable<Registration['gateway']> = Object.values(operations).map(operation => ({
  service: 'service-operations', path: operation.path, methods: [operation.method],
  roles: ['buyer'], maxBodyBytes: 16384, maxResponseBytes: 65536,
}));
export const outcomeFragments: readonly Fragment[] = (['C14', 'S04'] as const).map(outcome => ({
  outcome, registration: { lane: 'L21', namespace: `job-outcomes-${outcome.toLowerCase()}`,
    routes: [], dictionaries: { en: {}, ar: {} },
    gateway: boundedGateway.filter(endpoint => Object.values(operations).some(operation =>
      operation.outcome === outcome && operation.path === endpoint.path)),
  }, migrations: [], receivers: [], destinations: [],
}));
// Provider metadata is not available yet; expose no executable destinations.
export default composeOutcomes([]).registration;

export type OutcomeEnvelope = {
  schema_version: 'l21.outcome.v1'; operation_id: string; subject_id: string;
  watch_id: string; actor_id: string; organization_id: string | null;
  expected_revision: number; revision: number; state: RecoveryState | 'current';
  pending_reason: string | null; next_actor: string | null; next_review_at: string | null;
};
type Transport = { request(method: string, path: string, reference: string,
  options: { body?: string; headers: Record<string, string>; maxResponseBytes: number }): Promise<Response | { kind: 'unavailable' }> };

/** Share one bounded service transport across all outcome operations. */
export function createOutcomeAdapter(dependency?: Transport) {
  return async (name: keyof typeof operations, envelope: OutcomeEnvelope) => {
    const operation = operations[name];
    if (!operation || !envelope.operation_id.trim() || !envelope.subject_id.trim()
      || !envelope.watch_id.trim() || !envelope.actor_id.trim()
      || envelope.schema_version !== 'l21.outcome.v1'
      || !Number.isSafeInteger(envelope.expected_revision) || envelope.expected_revision < 0) {
      throw new Error('Invalid outcome request');
    }
    const fields = ['schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id',
      'organization_id', 'expected_revision', 'revision', 'state', 'pending_reason', 'next_actor', 'next_review_at'];
    if (Object.keys(envelope).length !== fields.length || fields.some(key => !Object.hasOwn(envelope, key))
      || ['organization_id', 'pending_reason', 'next_actor', 'next_review_at'].some(key => {
        const value = envelope[key as keyof OutcomeEnvelope];
        return value !== null && typeof value !== 'string';
      }) || !Number.isSafeInteger(envelope.revision) || envelope.revision < 0
      || !['current', 'pending', 'unavailable', 'denied', 'stale'].includes(envelope.state)) {
      throw new Error('Invalid outcome envelope');
    }
    const body = JSON.stringify(envelope);
    if (new TextEncoder().encode(body).byteLength > 16384) throw new Error('Outcome request exceeds budget');
    const command = operation.method !== 'GET';
    if (!dependency) return dependencyRecovery(envelope.operation_id, command);
    const path = operation.path.replace(':id', encodeURIComponent(envelope.subject_id));
    const requestPath = command ? path : `${path}?expected_revision=${envelope.expected_revision}`;
    try {
      const response = await dependency.request(operation.method,
        requestPath, envelope.operation_id,
        { headers: { 'Content-Type': 'application/json' },
          body: command ? body : undefined, maxResponseBytes: 65536 });
      if ('kind' in response) return dependencyRecovery(envelope.operation_id, command);
      if (!response.ok) return dependencyRecovery(envelope.operation_id, command, response.status);
      const result = await response.json() as OutcomeEnvelope;
      if (result === null || typeof result !== 'object' || Array.isArray(result)
        || Object.keys(result).length !== fields.length || fields.some(key => !Object.hasOwn(result, key))
        || ['organization_id', 'pending_reason', 'next_actor', 'next_review_at'].some(key => {
          const value = result[key as keyof OutcomeEnvelope];
          return value !== null && typeof value !== 'string';
        })) return dependencyRecovery(envelope.operation_id, command);
      for (const key of ['schema_version', 'operation_id', 'subject_id', 'watch_id', 'actor_id',
        'organization_id', 'expected_revision'] as const) {
        if (result[key] !== envelope[key]) return dependencyRecovery(envelope.operation_id, command);
      }
      if (!Number.isSafeInteger(result.revision) || result.revision < envelope.expected_revision
        || !['current', 'pending', 'unavailable', 'denied', 'stale'].includes(result.state)
        || !Object.hasOwn(result, 'pending_reason') || !Object.hasOwn(result, 'next_actor')
        || !Object.hasOwn(result, 'next_review_at')) return dependencyRecovery(envelope.operation_id, command);
      return result;
    } catch { return dependencyRecovery(envelope.operation_id, command); }
  };
}

export type RecoveryState = 'pending' | 'unavailable' | 'denied' | 'stale';

/** A failed command response cannot establish whether the command took effect. */
export function dependencyRecovery(operationId: string, command: boolean, status?: number) {
  if (!operationId.trim()) throw new Error('Missing operation reference');
  const state: RecoveryState = status === 403 ? 'denied' : status === 409 ? 'stale'
    : command ? 'pending' : 'unavailable';
  const messages = {
    pending: { en: 'The result is pending. Check the same action reference.', ar: 'النتيجة قيد الانتظار. تحقق باستخدام مرجع الإجراء نفسه.' },
    unavailable: { en: 'This action is unavailable. Try again later.', ar: 'هذا الإجراء غير متاح. حاول مرة أخرى لاحقًا.' },
    denied: { en: 'You do not have current permission for this action.', ar: 'ليس لديك إذن حالي لتنفيذ هذا الإجراء.' },
    stale: { en: 'The record changed. Review the current version before continuing.', ar: 'تغير السجل. راجع النسخة الحالية قبل المتابعة.' },
  };
  return { operation_id: operationId, state, message: messages[state],
    next_action: state === 'pending' ? 'check_same_operation' : state === 'stale' ? 'review_current_revision'
      : state === 'denied' ? 'review_current_access' : 'retry_same_operation' };
}
