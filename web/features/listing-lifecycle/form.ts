import type { Action, Command } from '@contracts/contracts-catalog/listing-lifecycle/v1';
export type Fields = { listing: string; watch: string; revision: string; proof: string; quote: string; quoteRevision: string; policy: string };
export const blank: Fields = { listing: '', watch: '', revision: '', proof: '', quote: '', quoteRevision: '', policy: '' };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function commandFor(fields: Fields, kind: Action, actor: string, organization: string | null, operation: string): Command {
  const positive = (value: string) => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value));
  if (!uuid.test(fields.listing) || !uuid.test(fields.watch) || !positive(fields.revision)
    || !fields.proof || fields.proof.length > 128 || fields.quote.length > 128 || fields.policy.length > 128
    || (kind !== 'pause' && (!fields.proof || !fields.quote || !fields.policy || !positive(fields.quoteRevision)))) throw new Error('invalid_form');
  return { schema_version: 'listing-lifecycle.v1', operation_id: operation,
    actor_id: actor, organization_id: organization, subject_id: fields.listing, watch_id: fields.watch,
    expected_revision: Number(fields.revision), kind, proof_id: fields.proof,
    quote_id: kind === 'pause' ? null : fields.quote, quote_revision: kind === 'pause' ? null : Number(fields.quoteRevision),
    policy_revision: kind === 'pause' ? null : fields.policy };
}
