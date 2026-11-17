export type ApprovalBindings = {
  watch_id:string;request_id:string;request_revision:number;brand_id:string;subject_id:string;approver_id:string;
  assessment_id:string;assessment_revision:number;quote_id:string;quote_revision:number;
  grant_id:string;grant_revision:number;amount_minor:number;currency:'USD';purpose:'brand_approval';consent_revision:number;assignment_revision:number;
};
/** Read-only availability is not execution authority. Only the available variant
 * carries bindings; commands independently recheck their current exact scope. */
export type DecisionReadiness =
  | {status:'available';bindings:ApprovalBindings;execution_authority:false}
  | {status:'unavailable';code:'approval_unavailable';execution_authority:false};
