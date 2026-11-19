export type FollowCommand = {
  schema_version:'seller-follows.v1'; operation_id:string; actor_id:string;
  organization_id:null; seller_id:string; expected_revision:number;
  following:boolean; alerts_enabled:boolean;
};
export type Follow = {seller_id:string;following:boolean;alerts_enabled:boolean;revision:number};
export type Receipt = {schema_version:'seller-follows.v1';operation_id:string;actor_id:string;organization_id:null;seller_id:string;state:'accepted';revision:number;result:Follow};
export type FollowPage = {items:Follow[];total:number;page:number;page_size:50};
export type NoticeCommand = {schema_version:'seller-follows.v1';operation_id:string;actor_id:string;organization_id:null;notice_id:string;expected_revision:number;action:'read'|'clear'};
export type NoticeReceipt = {schema_version:'seller-follows.v1';operation_id:string;actor_id:string;organization_id:null;notice_id:string;state:'accepted';revision:number;read_at:string|null;cleared_at:string|null};
