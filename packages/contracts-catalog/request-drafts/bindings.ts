export type WatchBinding = {
  operation_id: string;
  source_revision: number;
  expected_binding_revision: number;
  request_revision: number;
  buyer_id: string;
  brand_id: string;
  watch_id: string;
};
export type AssignmentBinding = WatchBinding & {
  assessor_id: string;
  approver_id: string;
  quality_reviewer_id: string;
  recovery_operator_id: string;
};
