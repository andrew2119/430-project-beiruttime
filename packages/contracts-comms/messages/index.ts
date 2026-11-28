export type Message = {sequence:number; actor_id:string; body:string; sent_at:string; preview:string; correction_required:boolean};
export type Thread = {id:string; kind:'listing'|'order'|'business'; subject_id:string; watch_id:string; organization_id:string|null; revision:number; source_revision:number; quote_revision:number|null; policy_revision:number; original_work_id:string|null; active_support:boolean; paid_held:boolean};
export type ThreadPage = {items:Thread[]; total:number; next_cursor:number|null};
export type Conversation = {thread:Thread; items:Message[]; total:number; next_cursor:number|null; unread:number; blocked:string[]};
export type Receipt = {schema_version:'communications.messages.v1'; operation_id:string; state:'accepted'; revision:number; sequence?:number};
export type Command = {operation_id:string; expected_revision:number; source_revision:number; quote_revision:number|null; policy_revision:number; kind:'send'|'read'|'block'|'unblock'|'report'|'appeal'|'delivery'; body?:string; target?:string; sequence?:number};
