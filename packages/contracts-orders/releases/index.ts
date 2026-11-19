export const conditions = [
  'stale_revision','binding_changed','sources_unavailable','economics_unaccepted',
  'payment_not_held','principal_unavailable','refund_active','recipient_unverified',
  'inspection_required','assurance_required','quality_required','receipt_required',
  'window_open','hold_active','hold_unknown','release_exists',
] as const;
export type Condition = typeof conditions[number];
export type Command = {
  schema_version:'orders.releases.v1'; operation_id:string; subject_id:string; watch_id:string;
  actor_id:string; organization_id:string|null; expected_revision:number;
  quote_id:string; quote_revision:number; policy_revision:number;
  recipient_id:string; recipient_revision:number;
};
export type Operation = Command & {
  state:'denied'|'pending'|'paid_out'|'unavailable'; revision:number; missing:Condition[];
  pending_reason:'transfer_pending'|'transfer_failed'|'response_unknown'|'dependency_unavailable'|null;
  next_actor:'operator'|'payout_operator'; responsible_operator_id:string|null; responsibility_revision:number|null;
  next_action:'review_conditions'|'reconcile_transfer'|'complete'; next_review_at:string;
  gross_minor:number|null; fee_minor:number|null; net_minor:number|null; simulated:true;
};
export type Snapshot = {
  subject_id:string; watch_id:string; organization_id:string|null; revision:number;
  quote_id:string; quote_revision:number; policy_revision:number; recipient_id:string; recipient_revision:number;
  active_release_operation_id:string|null;
  currency:'USD'; principal_minor:number; buyer_fee_minor:number; business_fee_minor:number; total_minor:number;
};
export type Preview = {snapshot:Snapshot; missing:Condition[]; closes_at:string|null; simulated:true};
