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

/** Orders owns this proof. A preview, eligibility verdict or cache cannot replace it. */
export type PlatformPaymentReadinessV3={
 buyer_id:string;order_id:string;order_kind:'brand'|'repair';watch_id:string;
 quote_id:string;quote_revision:number;currency:'USD';total_minor:number;
 payment_operation_id:string|null;payment_revision:number;
 state:'paid_held'|'pending'|'unpaid';
};
export type RetainedFinancialQuoteV3={
 quote_id:string;quote_revision:number;buyer_id:string;source_id:string;source_revision:number;
 currency:'USD';price_minor:number;buyer_fee_minor:number;seller_commission_minor:number;
 seller_net_minor:number;shipping_minor:number;tax_minor:number;payable_minor:number;
 schedule_id:'usd-v2'|'usd-job-v2';policy_revision:2;rounding:'half_up';minor_unit_exponent:2;
 sample:boolean;expires_at:string|null;reviewed_at:string|null;
 selected_line_ids:string[];terms_digest:string|null;return_fee_minor:number|null;
 accepted_fee_lines:{assessment:boolean;return_transport:boolean};authority:'retained_read_only';
};
