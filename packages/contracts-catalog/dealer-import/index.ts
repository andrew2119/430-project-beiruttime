export type ImportRow = {row: number; state: 'draft'|'invalid'|'duplicate'; listing_id: string|null};
export type ImportResult = {schema_version: 'dealer-import.v1'; operation_id: string; subject_id: null; watch_id: null; actor_id: string; organization_id: string; expected_revision: 0; pending_reason: null; next_actor: null; next_review_at: null; state: 'succeeded'; revision: 1; total: number; items: ImportRow[]; offset: number; limit: number};
export const importLimits = {bytes: 1000000, rows: 1000, page: 50} as const;
