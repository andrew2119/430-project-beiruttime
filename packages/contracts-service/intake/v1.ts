export type OpeningAcceptanceV1 = {
  quote_id: string;
  quote_revision: number;
  accepted_terms_revision: number;
  consent_revision: number;
};
export type AssessmentCustodyV1 = {
  watch_id: string;
  watch_revision: number;
  receipt_id: string;
  receipt_revision: number;
  incident_revision: number;
};
export type IntakeCommandV1 = {order_id:string;custody_receipt_id:string|null;serial:string;reference:string;movement:string;received_condition:string;accessories:string;reported_issue:string;assessed_issue:string;diagnostic_opening_permission:boolean;no_polish_acknowledged:boolean;fee_acknowledged:boolean;fee_minor:number;currency:'USD'|'LBP';opening_acceptance?:OpeningAcceptanceV1|null;reviewed_assessment_custody?:AssessmentCustodyV1;reviewed_receipt_revision?:AssessmentCustodyV1};
export type IntakeEventV1 = {record_id:string;order_id:string;organization_id:string;state:'awaiting_intake'|'received';revision:number;custody_receipt_id:string|null};
export type IntakeEvidenceUploadV1 = {safe_photo_declared?:boolean;kind:'condition_photo'|'prior_owner_record';media_type:'image/jpeg'|'image/png'|'image/webp'|'application/pdf';content_base64:string};
export type CustodyReceiptV1 = {id:string;order_id:string;organization_id:string;received_at:string;revision:number;valid:true};
export type IntakeOperationReceiptV1 = {
  operation_id: string;
  organization_id: string;
  record_id: string;
  order_id: string;
  revision: number;
  kind: 'save' | 'evidence';
  maintenance_request_id?: string | null;
};
export type IntakeOperationCommandV1 = {
  action: 'lookup' | 'close';
  operation_id: string;
};
