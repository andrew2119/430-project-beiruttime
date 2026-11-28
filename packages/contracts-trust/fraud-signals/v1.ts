export type Reason = {kind:'exact_photo_reuse'|'repeated_pair'; count:number};
export type SignalResult = {
  schema_version:'fraud-signals.v1'; operation_id:string; subject_id:string; watch_id:string;
  actor_id:string; organization_id:string; expected_revision:number; source_revision:number;
  state:'review_required'|'no_observable_signal'; revision:number; reasons:Reason[];
  pending_reason:null; next_actor:string; next_review_at:string;
};
export type SignalPage = {items:SignalResult[]; total:number; page:number; page_size:number};
