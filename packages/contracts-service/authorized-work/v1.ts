export type WorkState = 'recorded' | 'pending' | 'paused';
export type WorkOperation = {
  schema_version: 'authorized-work.v1'; operation_id: string; subject_id: string;
  watch_id: string; actor_id: string; organization_id: string; expected_revision: number;
  source_revision:number; quote_id:string; quote_revision:number; policy_revision:number;
  state: WorkState; revision: number; pending_reason: string | null;
  next_actor: string; next_review_at: string; release_eligible: false;
};
export type WorkContext = {
  subject_id: string; watch_id: string; actor_id: string; organization_id: string;
  expected_revision: number; source_revision: number; quote_id: string;
  quote_revision: number; policy_revision: number;
  responsible_actor_id:string; server_now: string; accepted_lines: { id: string; label: string }[];
};
