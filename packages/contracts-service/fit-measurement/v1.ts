export type FitCommand = {
  schema_version:'fit-measurement.v1'; operation_id:string; subject_id:string; watch_id:string; organization_id:string;
  expected_revision:number; source_revision:number; circumference:string; unit:'cm'|'mm';
  method:'tape'|'string_and_ruler'; source:'buyer_measured'; target:'close'|'comfortable'|'loose'; final_fit_pass:false;
};
export type FitRecord = {
  schema_version:'fit-measurement.v1'; operation_id:string; subject_id:string; watch_id:string; actor_id:string; organization_id:string;
  expected_revision:number; source_revision:number; state:'recorded'; revision:number; circumference_mm:number;
  method:FitCommand['method']; source:'buyer_measured'; target:FitCommand['target']; final_fit_pass:false;
  recorded_at:string; pending_reason:null; next_actor:null; next_review_at:null;
};
export type FitContext = {subject_id:string; watch_id:string; organization_id:string; source_revision:number; record:FitRecord|null};
export const operations = {
  context:{method:'GET',path:'/v1/fit-measurement/context'},
  record:{method:'POST',path:'/v1/fit-measurement/records'},
} as const;
