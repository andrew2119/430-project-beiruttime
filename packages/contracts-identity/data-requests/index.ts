export const domains = ['identity','catalog','auction','pricing','orders','eligibility','service-operations','communications','trust'] as const;
export type Domain = typeof domains[number];
export type RequestKind = 'export'|'delete';
export type HoldReason = 'active_sale'|'custody'|'payout'|'dispute'|'financial'|'audit'|'active_case';
export type RequestState = 'pending'|'partial'|'held'|'complete';
export interface DataOperation {
  schema_version: 'data-requests.v1'; operation_id:string; subject_id:string;
  watch_id:null; actor_id:string; organization_id:string|null; expected_revision:number;
  kind:RequestKind; state:RequestState; revision:number; policy_revision:'D31.v1';
  responsible_operator_id:string; support_due_at:string; escalation_at:string;
  submitted_at:string; due_at:string; pending_reason:'domain_acknowledgements'|'obligations'|'file_cleanup'|null;
  next_action:'await_domains'|'review_hold'|'retry_domain'|'remove_export_files'|null;
  next_actor:'domain'|'operator'|null; next_review_at:string|null;
  domains:Partial<Record<Domain,{state:'deleted'|'redacted'|'retained'|'exported'|'failed'; reasons:HoldReason[]}>>;
  export_available:boolean; export_expires_at:string|null;
}
export interface DataPage {items:DataOperation[]; total:number; page:number; page_size:number}
export interface DataCommand {schema_version:'data-requests.v1'; operation_id:string; kind:RequestKind; expected_revision:0}
export interface DomainCommand {
  command_id:string; operation_id:string; domain:Domain; actor_id:string; subject_id:string;
  organization_id:string|null; kind:RequestKind; expected_revision:number; policy_revision:'D31.v1';
}
export interface DomainReceipt {
  receipt_id:string; domain:Domain; operation_id:string; expected_revision:number;
  source_revision:number; facts_revision:number; policy_revision:'D31.v1';
  state:'deleted'|'redacted'|'retained'|'exported'|'failed'; reasons:HoldReason[];
  next_review_at:string|null; obligations_closed_at:string|null;
}
