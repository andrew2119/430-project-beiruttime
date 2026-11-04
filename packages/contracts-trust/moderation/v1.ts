export type ModerationTarget = 'listing'|'user'|'message';
export type ModerationAction = 'warn'|'hide'|'suspend'|'reinstate'|'dismiss';
export type ModerationReportV1 = {target_kind:ModerationTarget;target_id:string;category:'counterfeit'|'misleading'|'harassment'|'payment_abuse'|'other';evidence:string};
export type ModerationAssignmentReleaseV1 = {reason:string};
export type ModerationDecisionV1 = {action:ModerationAction;reason:string};
export type ModerationDecisionEventV1 = {case_id:string;target_kind:ModerationTarget;target_id:string;action:ModerationAction;revision:number;preserve_transaction_duties:true};
export type CaseSummaryV1 = {id:string;target_kind:ModerationTarget;target_id:string;category:string;status:'open'|'assigned'|'decided'|'appealed';revision:number;assigned_to:string|null;created_at:string;can_claim?:boolean;can_release?:boolean};
