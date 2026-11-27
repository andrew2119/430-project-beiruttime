export type Decision = 'consent'|'no_polish';
export type Area = {
  area_id:string;name_en:string;name_ar:string;original:'brushed'|'mirror'|'mixed'|'unknown';
  desired:'brushed'|'mirror'|'preserve';material_known:boolean;preservation_assessed:boolean;material_en:string;material_ar:string;
  coating:'absent'|'present'|'unknown';plating:'absent'|'thin'|'present'|'unknown';
  engraving:'absent'|'present'|'unknown';preservation_en:string;preservation_ar:string;
  assessed_action:'polish'|'brush'|'no_polish';suitable:boolean;
};
export type Terms = {
  revision:number;fee_en:string;fee_ar:string;return_en:string;return_ar:string;
  assurance_en:string;assurance_ar:string;support_path:'/inbox';
};
export type Source = {
  terms:Terms;
  subject_id:string;watch_id:string;buyer_id:string;organization_id:string;
  source_revision:number;assessment_revision:number;quote_id:string;quote_revision:number;
  policy_revision:number;commitment_id:string;current:boolean;assigned:boolean;retained:boolean;
  currency:'USD';total_minor:number;valid_until:string;areas:readonly Area[];
};
export type Command = {
  schema_version:'finish.v1';operation_id:string;subject_id:string;watch_id:string;actor_id:string;
  organization_id:string;expected_revision:number;source_revision:number;assessment_revision:number;
  quote_id:string;quote_revision:number;policy_revision:number;
  choices:readonly {area_id:string;decision:Decision}[];
};
export type Result = Pick<Command,'schema_version'|'operation_id'|'subject_id'|'watch_id'|'actor_id'|'organization_id'|'expected_revision'> & {
  state:'recorded'|'pending';revision:number;pending_reason:'source_unavailable'|null;
  next_actor:'buyer'|null;next_review_at:string|null;
};
export type Detail = {source:Source;revision:number;choices:Command['choices']};
