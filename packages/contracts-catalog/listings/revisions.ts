import type { WatchFacts } from './v1';
export type ListingRevision={revision:number;actor_id:string;reason:string;before_facts:WatchFacts;after_facts:WatchFacts;created_at:string};
export type ListingRevisionHistory={pending_operation_id:string|null;items:ListingRevision[]};
