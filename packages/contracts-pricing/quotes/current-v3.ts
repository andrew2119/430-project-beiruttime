/** Exact price validity, never payment, custody, eligibility or execution authority. */
export type CurrentQuoteV3={
 quote_id:string;quote_revision:number;buyer_id:string;source_id:string;source_revision:number;
 kind:'offer'|'brand'|'repair'|'purchase'|'winner';currency:'USD';total_minor:number;
 listing_id:string|null;listing_revision:number|null;assessment_id:string|null;assessment_revision:number|null;
 organization_id:string|null;expires_at:string|null;accepted_at:string|null;selected_line_ids:string[];terms_digest:string|null;
 schedule_id:'usd-v2'|'usd-job-v2';policy_revision:2;rounding:'half_up';status:'valid';
 economics:'preview'|'committed';execution_authority:'not_granted';
 accepted_fee_lines:{assessment:boolean;return_transport:boolean};
};
export type FixedPurchaseCommitV3={buyer_id:string;order_id:string;quote_revision:number;total_minor:number;committed_at:string};
