export type RefundCommand = Readonly<{
  schema_version:'refunds.v1';operation_id:string;subject_id:string;watch_id:string;
  actor_id:string;organization_id:string;expected_revision:number;source_revision:number;
  quote_id:string;quote_revision:number;policy_revision:number;basis_id:string;
  amount_minor:number;currency:'USD';
}>;
export type RefundOperation = Readonly<{
  schema_version:'refunds.v1';operation_id:string;subject_id:string;watch_id:string;
  actor_id:string;organization_id:string;expected_revision:number;
  state:'pending'|'confirmed'|'declined';revision:number;
  pending_reason:'reconciliation'|'processing'|null;next_actor:'payout_operator'|null;
  next_review_at:string|null;amount_minor:number;currency:'USD';simulated:true;
}>;
export type RefundCode = 'denied'|'stale'|'basis_required'|'return_required'|'cap_exceeded'|'pending'|'unavailable'|'conflict';
