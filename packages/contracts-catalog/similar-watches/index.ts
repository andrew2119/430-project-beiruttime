export type SimilarQuery = { operation_id:string; subject_id:string; expected_revision:number; offset:number };
export type SimilarWatch = { id:string; watch_id:string; revision:number; title:string; brand:string; reference:string; currency:'USD'; price_minor:number|null; available:boolean; sample:boolean };
export type SimilarRule = 'reference'|'brand'|'price_band';
export type SimilarResult = {
  schema_version:'similar-watches.v1'; operation_id:string; subject_id:string; watch_id:string|null;
  actor_id:null; organization_id:null; expected_revision:number; state:'ready'|'empty'|'stale'|'denied'|'unavailable';
  revision:number|null; pending_reason:'current_source_unavailable'|null; next_actor:'viewer'; next_review_at:null;
  rules_version:'reference-brand-band.v1'; items:{watch:SimilarWatch;rule:SimilarRule}[];
  total:number; offset:number; next_offset:number|null;
};
