export type Source = 'trust'|'orders'|'service-operations';
export type Outcome = 'accepted'|'denied'|'pending'|'cancelled';
export type AuditQuery = {
  schema_version:'audit-references.v1'; operation_id:string; organization_id:string;
  actor_id?:string; resource_id?:string; outcome?:Outcome; after:string; before:string;
  offset:number; limit:number; expected_revision?:number;
};
export type AuditReference = {
  operation_id:string; subject_id:string; watch_id:string|null; actor_id:string; organization_id:string;
  expected_revision:number; state:Outcome; revision:number; occurred_at:string;
  reason_code:'scope_changed'|'permission_changed'|'record_changed'|'review_recorded'|'awaiting_owner';
  reason_reference:string; pending_reason:'owner_pending'|null; next_actor:string|null; next_review_at:string|null;
};
export type OwnerPage = {
  schema_version:'audit-references.v1'; operation_id:string; organization_id:string; reader_id:string;
  query:AuditQuery; revision:number; items:AuditReference[]; total:number; next_offset:number|null;
};
export type ResultState = 'ready'|'empty'|'denied'|'stale'|'pending'|'unavailable';
export type SourceResult = {source:Source;state:ResultState;page:OwnerPage|null};
export type AuditResult = {schema_version:'audit-references.v1';operation_id:string;results:SourceResult[]};
export type OperationResult = {schema_version:'audit-references.v1';source:Source;state:ResultState;item:AuditReference|null};
