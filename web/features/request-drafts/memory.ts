import type { DraftInput } from '@contracts/contracts-catalog/request-drafts';
// Memory-only neutral intent survives locale navigation; never credentials or evidence.
export type PendingDraft={form:DraftInput;id:string|null;revision:number;key:string};
export type DraftMemory={owner:string;id:string|null;revision:number;form:DraftInput;dirty?:boolean;pending?:PendingDraft|null};
let current:DraftMemory|null=null;
let generation=0;
export function draftMemoryEpoch(){return generation;}
export function recall(owner:string){if(current?.owner!==owner)current=null;return current;}
export function remember(value:DraftMemory,expectedGeneration:number){if(expectedGeneration===generation)current=value;}
// Fence late async answers before clearing; a prior profile cannot repopulate private intent.
export function purge(){generation++;current=null;}
