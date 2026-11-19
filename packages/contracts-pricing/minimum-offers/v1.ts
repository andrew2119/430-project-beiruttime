export type Command = Readonly<{
  schema_version: 1; operation_id: string; actor_id: string; organization_id: string;
  subject_id: string; watch_id: string; expected_revision: number; source_revision: number;
  policy_revision: number; quote_id: string; quote_revision: number; minimum_minor: number | null;
}>;
export type Rule = { revision: number; minimum_minor: number | null };
export type PrivateEnvelope = Pick<Command,
  'schema_version' | 'operation_id' | 'subject_id' | 'watch_id' | 'actor_id' |
  'organization_id' | 'expected_revision'> & {
  revision: number | null; pending_reason: 'source_unavailable' | null;
  next_actor: 'seller' | null; next_review_at: null;
};
export type Result = (PrivateEnvelope & Partial<Pick<Rule, 'minimum_minor'>> & {
  state: 'saved' | 'stale' | 'pending' | 'unavailable';
}) | { schema_version: 1; operation_id: string; state: 'denied' };
export type OfferResult = { state: 'declined' | 'review_required' };
