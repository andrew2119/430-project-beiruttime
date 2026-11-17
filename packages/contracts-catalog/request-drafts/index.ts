export type DraftInput = { configuration_id?:string|null; configuration_revision?:number|null; brand_id: string|null; kind: 'customization'|'service'; watch_context: 'owned_watch'|'seller_base'|'undecided'; watch_reference: string; scope_intent: string; notes: string; options: Partial<Record<'color'|'material'|'movement'|'dial'|'sophistication',string>> };
export type RequestDraft = DraftInput & { submitted_request_id?:string|null; id: string; revision: number; updated_at: string; status: 'draft'; approved: false; payment_authority: false };
export type ConfigurationIntent = {configuration_id:string;configuration_revision:number;brand_id:string;base_model:string;caliber:string;options:DraftInput['options'];selection_summary:{kind:string;component:string;option_id:string;option_revision:number;current:boolean}[]};
export type DraftReadiness = { draft: RequestDraft; brand: unknown; options: unknown; intake: unknown; configuration?:{status:string;code?:string;data?:ConfigurationIntent}; sections: Record<'quote'|'consent'|'work'|'quality'|'collection',{status:string; reason:string}> };

export type DraftPage = {items:RequestDraft[];total:number;next_cursor:string|null};
