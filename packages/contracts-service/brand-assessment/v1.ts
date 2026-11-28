export type Kind = 'claim' | 'release' | 'reassign' | 'assess' | 'correct';
export type Feasibility = 'feasible' | 'incompatible' | 'parts_unavailable' | 'manual';
export type Current = {
  operation_id?: string; current_watch_id?: string;
  schema_version: 'brand-assessment.v1'; subject_id: string; watch_id: string;
  actor_id: string; organization_id: string; request_revision: number;
  current_request_revision?: number; current_capability_revision?: number; assignment_revision: number; capability_revision: number; revision: number;
  current_scope?: { base_id: string; caliber_id: string; option_snapshots: { dimension: string; option_id: string; option_revision: number }[] };
  assessment_id?: string; assessment_revision?: number; assessor_id?: string;
  feasibility?: Feasibility; parts?: string[]; limitations?: string; lead_time_basis?: string;
  responsible_operator_id?: string | null; next_action?: string; escalation_at?: string;
  state: string; claimant: string | null; pending_reason: string | null;
  next_actor: string; next_review_at: string | null;
};
export type Command = {
  schema_version: 'brand-assessment.v1'; operation_id: string; subject_id: string;
  watch_id: string; actor_id: string; organization_id: string; expected_revision: number;
  request_revision: number; assignment_revision: number; capability_revision: number;
  kind: Kind; replacement_id: string | null; feasibility: Feasibility | null;
  parts: string[]; limitations: string; lead_time_basis: string; reason: string;
};
