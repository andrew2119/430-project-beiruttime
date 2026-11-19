export type Action = 'cancel' | 'retract' | 'remove_bid' | 'seller_end';
export type Command = {
  operation_id: string; subject_id: string; watch_id: string; actor_id: string;
  organization_id: string; expected_revision: number; action: Action; reason: string;
  target_bidder_id: string | null; quote_id: string; quote_revision: number;
  policy_revision: number; assignment_revision: number;
};
export type Receipt = Pick<Command, 'operation_id' | 'subject_id' | 'watch_id' | 'actor_id' | 'organization_id' | 'expected_revision' | 'quote_id' | 'quote_revision' | 'policy_revision' | 'assignment_revision'> & {
  schema_version: 'auction-exceptions.v1'; state: 'pending' | 'denied' | 'acknowledged';
  revision: number; code: string; pending_reason: string | null;
  next_actor: string | null; next_review_at: string | null;
};
export type Context = Omit<Command, 'operation_id' | 'action' | 'reason' | 'target_bidder_id'>;
