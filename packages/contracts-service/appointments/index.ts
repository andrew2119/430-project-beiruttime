export type Purpose = 'intake'|'assessment'|'fit'|'collection';
export type Binding = {
  subject_id:string; watch_id:string; actor_id:string; organization_id:string;
  source_revision:number; policy_revision:number; assignment_revision:number;
  quote_id:string|null; quote_revision:number|null;
};
export type Command = Binding & {
  schema_version:'appointments.v1'; operation_id:string; appointment_id:string;
  expected_revision:number; kind:'request'|'confirm'|'reschedule'|'cancel'; purpose:Purpose;
  civil_time:string; timezone:'Asia/Beirut'; selected_instant:string|null;
  repeated_time_confirmed:boolean; duration_minutes:number;
};
export type Visit = Binding & {
  schema_version:'appointments.v1'; operation_id:string; appointment_id:string; expected_revision:number;
  purpose:Purpose; civil_time:string; timezone:'Asia/Beirut'; instant:string; duration_minutes:number;
  repeated_time_confirmed:boolean; state:'requested'|'confirmed'|'cancelled'; revision:number;
  confirmed_by:string|null; pending_reason:'business_confirmation'|null; next_actor:'business'|'none';
  next_review_at:string|null; custody_received:false; work_authorized:false; physical_release_allowed:false;
};
