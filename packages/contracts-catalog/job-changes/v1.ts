export type ChangeState = 'pending_hold' | 'awaiting_reapproval' | 'pending_resume' | 'reapproved';
export interface ChangeOperation {
 schema_version: 'job-changes.v1'; operation_id: string; subject_id: string; watch_id: string;
 actor_id: string; organization_id: string; expected_revision: number; revision: number;
 state: ChangeState; pending_reason: string | null; next_actor: string; next_review_at: string;
 active_scope_id:string;invalidated:('quote'|'eligibility'|'brand_decision'|'buyer_acceptance')[];
 execution_authority: false;
}
export interface ChangeCommand {
 operation_id:string;subject_id:string;watch_id:string;actor_id:string;organization_id:string;
 responsible_operator_id:string;expected_revision:number;order_id:string;source_scope_id:string;proposed_scope_id:string;
 retained_quote_id:string;retained_quote_revision:number;reason:string;schema_version:'job-changes.v1';
}
export interface ApprovalCommand {
 operation_id:string;scope_id:string;scope_revision:number;assessment_id:string;assessment_revision:number;
 quote_id:string;quote_revision:number;consent_revision:number;eligibility_revision:number;policy_revision:number;
 approval_revision:number;acceptance_revision:number;payment_revision:number;total_minor:number;business_fee_minor:number;
 assessor_id:string;approver_id:string;quality_reviewer_id:string;eligibility_reviewer_id:string;accepted_at:string;currency:'USD';
}
export interface ChangeReview {
 change:ChangeCommand; approval:ApprovalCommand|null;
 scope:{en:string;ar:string};terms:{en:string;ar:string};
}
