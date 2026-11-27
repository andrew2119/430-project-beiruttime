export type Capability = 'maintenance'|'cleaning'|'polishing'|'repair'|'bracelet_fit'|'customization';
export type Purpose = 'servicing'|'customization';
export type Business = { organization_id:string;revision:number;display_name:string;kind:'brand'|'dealer';sample:boolean;capabilities:Capability[];contact:string;visit_en:string;visit_ar:string;scope_en:string;scope_ar:string };
export type Choice = {id:string;organization_id:string;capability:Capability;purpose:Purpose;revision:number;profile_revision:number};
export type Movement = {id:string;brand_id:string;revision:number;label_en:string;label_ar:string;caliber:string;cases:string[];dials:string[];hands:string[];functions:string[];compatibility_rules?:{case:string;dial:string;hands:string;functions:string[];state:'supported_for_review'|'incompatible'|'parts_unavailable'}[];quote_minor:number;currency:'USD'};
export type Configuration = {case:string;dial:string;hands:string;functions:string[]};
export type MovementSelection = {id:string;brand_id:string;option_id:string;revision:number;option_revision:number;configuration:Configuration;status:'supported_for_review'|'manual_review'|'incompatible'|'parts_unavailable';unsupported:string[];physical_feasibility_pass:false;quote_impact:{minor:number;currency:'USD';indicative:true}};
