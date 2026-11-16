export type AssessedLine = { id:string; label:string; kind:'part'|'labor'; mandatory:boolean; amount_minor:number; part_reference:string|null };
export type Amounts = { parts_minor:number; labor_minor:number; assessment_fee_minor:number; platform_fee_minor:number; seller_commission_minor:number; seller_net_minor:number; payable_minor:number };
export type AssessedQuote = {
 id:string; revision:number; kind:'brand'|'repair'; source_id:string; source_revision:number;
 assessment_id:string; assessment_revision:number; buyer_id:string; organization_id:string; author_id:string;
 diagnosis:string; currency:'USD'; lines:AssessedLine[]; assessment_fee_minor:number; return_fee_minor:number;
 warranty_terms:string; modification_terms:string; indicative_min_minor:number; indicative_max_minor:number;
 indicative_basis:string; lead_time_days:number; expires_at:string; economics_expires_at:string|null; terms_digest:string;
 policy:{sample:true;schedule_id:'sample-v1'|'usd-job-v2';revision:1|2;buyer_fee_bps:number;business_fee_bps?:number;seller_commission_bps:number;rounding:'half_up';minor_unit_exponent:2};
 full_total:Amounts; state:'issued'|'accepted'|'superseded'|'declined_return_held'|'expired_return_held';
 decision:null|{state:string;actor_id:string;accepted_at:string|null;selected_line_ids:string[];amounts:Amounts;terms_digest:string;accepted_fee_lines:{assessment?:boolean;return_transport?:boolean}};
};
export type QuoteContext = { source_id:string; source_revision:number; assessment_id:string; assessment_revision:number; currency:'USD'; diagnosis:string; lines:Omit<AssessedLine,'amount_minor'>[] };
