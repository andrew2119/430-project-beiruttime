export type Economics = Readonly<{
  quote_id:string; quote_revision:number; policy_revision:number; currency:'USD';
  price_minor:number; buyer_fee_minor:number; seller_commission_minor:number;
  total_minor:number; terms_revision:number;
}>;
export type Counter = Readonly<{
  id:string; subject_id:string; watch_id:string; seller_id:string; buyer_id:string;
  organization_id:string|null; revision:number;
  state:'sent'|'superseded'|'rejected'|'closed'|'accepted'; economics:Economics;
  sent_at:string; expires_at:string; predecessor_id:string|null;
}>;
export type Command = Readonly<{
  schema_version:'counteroffers.v1'; operation_id:string; subject_id:string; watch_id:string;
  actor_id:string; organization_id:string|null; expected_revision:number; source_revision:number; authority_revision:number;
  kind:'propose'|'accept'|'reject'; economics:Economics; reviewed_revision:number|null;
}>;
export type Operation = Readonly<{
  schema_version:'counteroffers.v1'; operation_id:string;
  subject_id:string; watch_id:string; actor_id:string; organization_id:string|null; expected_revision:number;
  state:'succeeded'|'denied'|'pending'|'unavailable'; code:string; revision:number;
  current:Counter|null; next_actor:'buyer'|'seller'|'support'; pending_reason:string|null;
  next_review_at:string|null; order_id:string|null;
}>;
