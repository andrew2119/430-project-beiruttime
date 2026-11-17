export type Check = { key: string; actual: string; satisfactory: boolean };
export type QualityLine = { line_id: string; tests: Check[]; condition: Check; fit: Check; returned_parts: Check };
export type QualityCommand = {
  schema_version: 'quality.v1'; operation_id: string; actor_id: string; organization_id: string;
  job_id: string; watch_id: string; expected_revision: number; scope_revision: number;
  work_revision: number; assignment_revision: number; quote_id: string; quote_revision: number;
  policy_revision: number; lines: QualityLine[];
};
export type QualityReceipt = { schema_version: 'quality.v1'; operation_id: string; job_id: string;
  watch_id: string; actor_id: string; organization_id: string; subject_id: string; expected_revision: number;
  quote_id: string; quote_revision: number; policy_revision: number; state: 'satisfactory' | 'rework';
  revision: number; scope_revision: number; work_revision: number; assignment_revision: number;
  pending_reason: null; next_actor: 'business'; next_review_at: null };

export type QualityLinePage = {
  schema_version: 'quality.v1'; offset: number; limit: 5; total: number;
  scope_revision: number; work_revision: number;
  lines: { line_id: string; test_keys: string[] }[];
};
