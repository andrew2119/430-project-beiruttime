export type MaintenanceRequestV1={schema_version:'service.maintenance.v1';operation_id:string;subject_id:string;watch_id:string;actor_id:string;organization_id:string;expected_revision:number;watch_revision:number;capability_revision:number;policy_revision:number;brand_id:string;intervention:'limited_maintenance'|'overhaul_assessment';reported_symptoms:string;known_modifications:string;photo_refs:string[];limited_assessment_permission:boolean};
export type MaintenanceResultV1=Pick<MaintenanceRequestV1,'schema_version'|'operation_id'|'subject_id'|'watch_id'|'actor_id'|'organization_id'|'expected_revision'|'watch_revision'|'capability_revision'|'policy_revision'|'brand_id'|'intervention'> & {request_id:string;pending_reason:string|null;next_actor:'customer'|'business'|'support';next_review_at:string|null} &
  ({state:'submitted';revision:1}|{state:'denied'|'stale'|'pending';revision:0});
export type MaintenanceContextV1={actor_id:string;subject_id:string;watch_id:string;watch_revision:number;destinations:{organization_id:string;brand_id:string;capability_revision:number;policy_revision:number;display_name:string;interventions:MaintenanceRequestV1['intervention'][]}[]};
export type MaintenanceAssessmentV1 = Pick<MaintenanceRequestV1,
  'watch_id' | 'brand_id' | 'intervention' | 'reported_symptoms' | 'known_modifications' | 'photo_refs'> & {
  request_id: string;
  revision: number;
  submitted_at: string;
  limited_assessment_permission: true;
};
export type MaintenanceAssessmentPhotoV1 = {
  photo_ref: string;
  media_type: 'image/jpeg' | 'image/png' | 'image/webp';
  content_base64: string;
};

export type MaintenanceAssessmentQueueV1 = {
  items: {request_id: string; delivered_at: string}[];
  total: number;
  next_offset: number | null;
};

export type MaintenancePhotoV1 = Pick<MaintenanceRequestV1,
  'watch_id' | 'organization_id' | 'brand_id' | 'intervention' |
  'watch_revision' | 'capability_revision' | 'policy_revision'> & {
  operation_id: string;
  request_operation_id: string;
  media_type: string;
  content_base64: string;
  safe_photo_declared: boolean;
};

export type MaintenanceDeliveryHoldV1 = {
  operation_id: string;
  operator_id: string;
  held_at: string;
  next_review_at: string;
  escalate_at: string;
  escalated_at: string | null;
  retry_in_progress: boolean;
  escalation_reviewed_at: string | null;
  first_response_at: string | null;
  first_response_overdue: boolean;
  next_action: 'review_and_retry_delivery' | 'respond_to_overdue_delivery' | 'resolve_escalated_delivery' |
    'review_active_escalation' | 'review_delivered_escalation' | 'monitor_escalated_retry';
};

export type MaintenancePhotoReceiptV1 = Omit<MaintenancePhotoV1,
  'media_type' | 'content_base64' | 'safe_photo_declared'> & {
  actor_id: string;
  subject_id: string;
  photo_ref: string;
  revision: 1;
};

export type MaintenanceDeliveryRecoveryCommandV1 = {
  held_at: string;
  action?: 'acknowledge' | 'retry' | 'review_escalation';
};
