import type { Registration } from '../registry-types';

// Existing public URLs remain with their original registrations.
const registration = {
  lane: 'L16',
  namespace: 'lane-wiring',
  routes: [],
  dictionaries: {
    en: { pending: 'The result is pending. Retry with the same action reference.', unavailable: 'The service is unavailable. Try again later.' },
    ar: { pending: 'النتيجة قيد الانتظار. أعد المحاولة باستخدام مرجع الإجراء نفسه.', unavailable: 'الخدمة غير متاحة. حاول مجددًا لاحقًا.' },
  },
  gateway: [],
  slots: [],
} satisfies Registration;

export default registration;

type Gateway = NonNullable<Registration['gateway']>[number];
const operations = {
  'intake.read.v1': { lane: 'L09', service: 'service-operations', path: '/v1/intake/records/:id', method: 'GET' },
  'intake.update.v1': { lane: 'L09', service: 'service-operations', path: '/v1/intake/records/:id', method: 'PUT' },
  'options.configuration.read.v1': { lane: 'L10', service: 'catalog', path: '/v1/brand-options/configurations/:id', method: 'GET' },
  'options.configuration.update.v1': { lane: 'L10', service: 'catalog', path: '/v1/brand-options/configurations/:id/:kind', method: 'PUT' },
  'operations.queue.read.v1': { lane: 'L09', service: 'communications', path: '/v1/operator-workspace/queues/:key', method: 'GET' },
} as const;

export type L16Operation = keyof typeof operations;

// Missing or ambiguous providers are unavailable; this never grants authority.
export function lookupL16Operation(id: L16Operation, entries: readonly Registration[]): Gateway | undefined {
  const operation = operations[id];
  if (!operation) return undefined;
  const providers = entries.filter(entry => entry.lane === operation.lane);
  if (providers.length !== 1) return undefined;
  const matches = entries.flatMap(entry => (entry.gateway ?? []).filter(endpoint =>
    endpoint.service === operation.service && endpoint.path === operation.path && endpoint.methods.includes(operation.method)
  ).map(endpoint => ({ lane: entry.lane, endpoint })));
  if (matches.length !== 1 || matches[0].lane !== operation.lane) return undefined;
  const endpoint = matches[0].endpoint;
  if (!endpoint.roles.length || endpoint.roles.includes('public') || endpoint.forwardCookies?.length) return undefined;
  for (const budget of [endpoint.maxBodyBytes, endpoint.maxResponseBytes]) {
    if (budget !== undefined && (!Number.isInteger(budget) || budget < 1 || budget > 16 * 1024 * 1024)) return undefined;
  }
  return { ...endpoint, methods: [operation.method], roles: [...endpoint.roles],
    maxBodyBytes: endpoint.maxBodyBytes ?? 65536,
    maxResponseBytes: endpoint.maxResponseBytes ?? 2 * 1024 * 1024 };
}
