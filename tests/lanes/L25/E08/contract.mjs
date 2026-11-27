// Development contracts only; provider bindings require connected verification.
export const schemaVersion = 'phone-journeys.v1';
export const journeys = Object.freeze([
  'bid', 'sell', 'customize', 'service', 'consent', 'pay', 'track', 'dispute',
]);
export const operations = Object.freeze(Object.fromEntries(journeys.map(name => [name, {
  schema_version: schemaVersion, operation: `phone.${name}.v1`,
  authority: name === 'pay' ? 'orders' : name === 'bid' ? 'auction' : 'current-provider',
  timeout_ms: 5000, max_attempts: 2, offline_queue: false,
}])));
export const states = ['loading', 'empty', 'denied', 'pending', 'error', 'retry', 'unavailable', 'confirmed'];
export const messages = Object.freeze({
  loading: ['Loading current details', 'جارٍ تحميل التفاصيل الحالية'],
  empty: ['No records. Return to the marketplace', 'لا توجد سجلات. ارجع إلى السوق'],
  denied: ['Access denied. Check your current account', 'الوصول مرفوض. تحقق من حسابك الحالي'],
  pending: ['Unconfirmed. Check the same action reference', 'غير مؤكد. تحقق من مرجع الإجراء نفسه'],
  error: ['Could not complete. Review and retry the same action', 'تعذر الإكمال. راجع الإجراء وأعد المحاولة بالمرجع نفسه'],
  retry: ['Retry the same action reference', 'أعد المحاولة بمرجع الإجراء نفسه'],
  unavailable: ['Details unavailable. Try again later', 'التفاصيل غير متاحة. حاول لاحقاً'],
  confirmed: ['Confirmed. View the current record', 'تم التأكيد. اعرض السجل الحالي'],
});
export function validateEnvelope(value) {
  if (!value || value.schema_version !== schemaVersion) throw Error('schema');
  for (const key of ['operation_id', 'subject_id', 'watch_id', 'actor_id']) {
    if (typeof value[key] !== 'string' || !value[key].length || value[key].length > 128) throw Error(key);
  }
  if (value.organization_id !== null && typeof value.organization_id !== 'string') throw Error('organization');
  for (const key of ['expected_revision', 'revision', 'policy_revision']) {
    if (!Number.isSafeInteger(value[key]) || value[key] < 0) throw Error(key);
  }
  for (const [id, revision] of [['assignment_id', 'assignment_revision'], ['quote_id', 'quote_revision']]) {
    if (value[id] === null && value[revision] === null) continue;
    if (typeof value[id] !== 'string' || !value[id].length || value[id].length > 128 ||
        !Number.isSafeInteger(value[revision]) || value[revision] < 0) throw Error(id);
  }
  if (!states.includes(value.state)) throw Error('state');
  for (const key of ['pending_reason', 'next_actor', 'next_review_at']) {
    if (!(key in value)) throw Error(key);
  }
  if (value.state === 'pending' && (!value.pending_reason || !value.next_actor ||
      !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value.next_review_at) ||
      !Number.isFinite(Date.parse(value.next_review_at)))) throw Error('pending recovery');
  return value;
}
export function sameBinding(left, right) {
  return ['operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision',
    'assignment_id', 'assignment_revision', 'quote_id', 'quote_revision', 'policy_revision']
    .every(key => left[key] === right[key]);
}
export function reconcile(request, response, current) {
  validateEnvelope(request);
  if (current.actor_id !== request.actor_id || current.organization_id !== request.organization_id || current.allowed !== true) return 'purge';
  if (['assignment_id', 'assignment_revision'].some(key => current[key] !== request[key])) return 'purge';
  if (current.revision !== request.expected_revision ||
      ['quote_id', 'quote_revision', 'policy_revision'].some(key => current[key] !== request[key])) return 'denied';
  if (!response) return 'pending';
  validateEnvelope(response);
  if (!sameBinding(request, response)) return 'denied';
  if (response.revision < request.expected_revision) return 'denied';
  return response.state;
}
export function money(value) {
  if (!Number.isSafeInteger(value) || value < 0) throw Error('integer USD cents required');
  return value;
}
export function beforeDeadline(now, deadline) {
  const utc = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/;
  if (![now, deadline].every(value => utc.test(value) && Number.isFinite(Date.parse(value)))) throw Error('UTC required');
  return Date.parse(now) < Date.parse(deadline);
}
