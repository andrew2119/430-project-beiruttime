export type Criteria = {q:string;brand:string;model:string;location:string;min_minor:number|null;max_minor:number|null;currency:'USD';sale_mode:''|'fixed'|'auction'|'offer';sort:'newest'|'price_asc'|'price_desc'|'ending_soon'};
export type Command = {schema_version:'saved-searches.v1';operation_id:string;subject_id:string;expected_revision:number;kind:'save'|'remove';name:string;criteria:Criteria;alerts_enabled:boolean};
export type SavedSearch = {id:string;revision:number;name:string;criteria:Criteria;alerts_enabled:boolean;state:'saved'|'removed';created_at:string};
export type Receipt = {schema_version:'saved-searches.v1';operation_id:string;subject_id:string;actor_id:string;organization_id:null;expected_revision:number;state:'saved'|'removed';revision:number;pending_reason:null;next_actor:null;next_review_at:null;result:SavedSearch};
export type Notice = {id:string;subscription_id:string;listing_id:string;watch_id:string;source_revision:number;event_time:string;sample:boolean;read:boolean;cleared:boolean;revision:number};
export type Page<T> = {items:T[];total:number;offset:number;limit:number};
