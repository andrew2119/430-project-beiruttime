import type { Command, Receipt } from '@contracts/contracts-catalog/listing-lifecycle/v1';
import { authenticatedRequest } from '@/features/identity/session';
const root = '/api/web/v1/catalog/v1/seller/listing-lifecycle';
export async function send(command: Command): Promise<Receipt> {
  const answer = await authenticatedRequest<Receipt>(`${root}/commands`, {
    method: 'POST', headers: { 'Idempotency-Key': command.operation_id, 'Content-Type': 'application/json' },
    body: JSON.stringify(command), signal: AbortSignal.timeout(4000),
  });
  if (!matches(command, answer)) throw new Error('invalid_receipt');
  return answer;
}
export function matches(command: Command, answer: unknown): answer is Receipt {
  if (!answer || typeof answer !== 'object' || Array.isArray(answer)) return false;
  const value = answer as Record<string, unknown>;
  const resultKeys = ['state', 'revision', 'pending_reason', 'next_actor', 'next_review_at',
    'listing_id', 'auction_id', 'previous_auction_id', 'responsible_operator_id', 'next_action', 'escalate_at'];
  const keys = [...Object.keys(command), ...resultKeys];
  if (Object.keys(value).length !== keys.length || !keys.every(key => Object.hasOwn(value, key))
    || !Object.entries(command).every(([key, expected]) => value[key] === expected)
    || !Number.isSafeInteger(value.revision) || (value.revision as number) < command.expected_revision) return false;
  const uuid = (id: unknown): id is string => typeof id === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
  const identifiers = ['listing_id', 'auction_id', 'previous_auction_id'];
  if (!identifiers.every(key => value[key] === null || uuid(value[key]))) return false;
  const utc = (time: unknown): time is string => typeof time === 'string'
    && /(?:Z|\+00:00)$/.test(time) && Number.isFinite(Date.parse(time));
  if (value.state === 'pending') return value.pending_reason === 'confirmation_required'
    && value.next_actor === 'support' && uuid(value.responsible_operator_id)
    && value.next_action === 'resolve_confirmation' && utc(value.next_review_at) && utc(value.escalate_at)
    && Date.parse(value.escalate_at) - Date.parse(value.next_review_at) === 86400000
    && identifiers.every(key => value[key] === null);
  if (value.next_actor !== null || value.next_review_at !== null
    || value.responsible_operator_id !== null || value.next_action !== null || value.escalate_at !== null) return false;
  if (value.state === 'denied') return ['committed', 'stale_revision', 'possession_required', 'terms_changed', 'ineligible']
    .includes(value.pending_reason as string) && identifiers.every(key => value[key] === null);
  return value.state === 'succeeded' && (value.revision as number) > command.expected_revision
    && value.pending_reason === null && uuid(value.listing_id)
    && (command.kind === 'relist' ? value.listing_id !== command.subject_id : value.listing_id === command.subject_id)
    && (value.previous_auction_id === null || command.kind === 'pause'
      || (value.auction_id !== null && value.auction_id !== value.previous_auction_id));
}
export async function lookup(command: Command): Promise<Receipt> {
  const answer = await authenticatedRequest<Receipt>(`${root}/operations/${encodeURIComponent(command.operation_id)}`, {
    signal: AbortSignal.timeout(4000),
  });
  if (!matches(command, answer)) throw new Error('invalid_receipt');
  return answer;
}
