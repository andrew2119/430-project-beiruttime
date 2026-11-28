export const schemaVersion = 'help-policies.v1' as const;
export const operations = {
  guidance: {method:'GET', path:'/v1/help-policies', scope:'public'},
  acceptedTerms: {method:'GET', path:'/v1/help-policies/accepted-terms/{record_id}', scope:'current-record'},
} as const;
export type HelpState = 'ready'|'pending'|'denied'|'stale'|'unavailable';
export type AcceptedTermsRequest = {
  operation_id:string; actor_id:string; organization_id:string|null;
  subject_id:string; watch_id:string; record_id:string; expected_revision:number;
};
export type AcceptedTerms = AcceptedTermsRequest & {
  schema_version:typeof schemaVersion; state:HelpState; revision:number|null;
  pending_reason:string|null; next_actor:string|null; next_review_at:string|null;
  artifact:null|{issuer:'E03'; policy_revision:string; accepted_at:string; en:string; ar:string};
};
export type HelpArticle = {id:string; en:{title:string;body:string}; ar:{title:string;body:string}};
