export type Dimension = 'color'|'material'|'dial'|'sophistication'|'movement';
export type Snapshot = {compatibility_status?:string;brand_id:string;base_model:string;caliber:string;selections:Record<Dimension,{option_id:string;option_revision:number;definition:Record<string,unknown>}>;reference_ids:string[];movement_mounting:Record<string,unknown>};
export type Validation = {status:'valid'|'incompatible'|'parts_unavailable'|'manual_assessment';fields:Record<string,string>;digest:string;snapshot:Omit<Snapshot,'selections'>&{selections:Partial<Snapshot['selections']>};physical_feasibility_pass:false;price_acceptance:false};
export type BrandRequest = {id:string;revision:number;draft_id:string;buyer_id:string;brand_id:string;status:'submitted';configuration_digest:string;configuration:Snapshot;watch_context:string;watch_reference:string;scope_intent:string;notes:string;created_at:string};
export type Submit = {draft_revision:number;configuration_id:string;configuration_revision:number;movement_selection_id:string;movement_revision:number;expected_digest:string};
export type Operation = {id:string;status:'succeeded';resource_id:string;request:BrandRequest};
