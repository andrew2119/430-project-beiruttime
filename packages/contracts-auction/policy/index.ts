export type PolicySnapshot = {policy_version:'fixed-end.v2';auction_id:string;revision:number;end_version:number;current_ends_at:string;server_time:string;frozen:boolean;reserve_set:boolean;mode:string;schedule_state:'scheduled'|'live'|'ended'|'ended_legacy_review'};
export type SellerPolicySnapshot = PolicySnapshot & {reserve_met:boolean;cancellation_eligible:boolean};
// These commands describe historic persisted requests only; no new purchase is admitted.
export type PrebidCommand = {expected_revision:number;quote_id:string};
export type LegacyOperationSnapshot = PrebidOutcome & {version:2;financial_state:'held';schedule_state:'within_schedule'|'ended_legacy_review';scheduled_ends_at:string};
export type PrebidOutcome = {operation_id:string;auction_id:string;status:'pending'|'succeeded'|'denied';code:string;reservation_id?:string;order_id?:string;quote_id?:string;revision?:number};
