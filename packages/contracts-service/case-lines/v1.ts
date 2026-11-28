export type CaseLineV1={line_id:string;kind:string;description:string;required:boolean;amount_minor:number;currency:'USD';assessment_id:string;assessment_revision:number};
export type CaseScopeV1={schema_version:'service.case-lines.v1';request_id:string;request_revision:number;revision:number;lines:CaseLineV1[];accepted_line_ids:string[]};
export type ScopeBindingV1={schema_version:'service.case-lines.v1';operation_id:string;actor_id:string;subject_id:string;organization_id:string;watch_id:string;request_id:string;request_revision:number;expected_revision:number;quote_id:string;quote_revision:number;policy_revision:number};
type LocalizedTerm = {en: string; ar: string};
export type RetainedTermsV1 = {
  lead_time: LocalizedTerm;
  fees: LocalizedTerm;
  return_terms: LocalizedTerm;
  assurance: LocalizedTerm;
  conditions: LocalizedTerm;
};
export type ScopeAcceptanceV1=ScopeBindingV1 & {accepted_line_ids:string[];total_minor:number;accepted_terms_revision:number;reviewed_terms:RetainedTermsV1};
export type ScopeReceiptV1 = ScopeBindingV1 & {
  revision: number;
  pending_reason: string | null;
  next_actor: 'customer' | 'business' | 'support';
  next_review_at: string | null;
  case_id?: string | null;
  assessment_id?: string | null;
  assessment_revision?: number | null;
} & (
  | {state: 'accepted'; accepted_terms_revision: number; terms_digest: string}
  | {state: 'denied' | 'stale' | 'pending'; accepted_terms_revision?: number | null; terms_digest?: string | null}
);
export type CurrentCaseScopeV1 = {
  actor_id: string;
  subject_id: string;
  organization_id: string;
  watch_id: string;
  quote_id: string;
  quote_revision: number;
  policy_revision: number;
  terms_revision: number;
  terms: RetainedTermsV1;
  total_minor: number;
  scope: CaseScopeV1;
};
export type CurrentCaseScopeResultV1 = {current: CurrentCaseScopeV1; acceptance: ScopeReceiptV1 | null};
