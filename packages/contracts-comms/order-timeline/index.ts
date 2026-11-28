export type Financial = {kind: 'gross' | 'collected_fee' | 'refund' | 'net' | 'payout'; state: 'pending' | 'confirmed' | 'blocked'; amount_minor: number; operation_id: string; revision: number; occurred_at: string; source: 'payments' | 'settlement'};
export type Source = 'orders' | 'payments' | 'inspection' | 'custody' | 'progress' | 'settlement';
export type Status = 'pending' | 'confirmed' | 'blocked' | 'unavailable' | 'not_applicable';
export type Party = 'buyer' | 'seller' | 'business' | 'operator' | 'authenticator';
export type Action = 'pay' | 'review' | 'receive' | 'inspect' | 'work' | 'reconcile' | 'wait';
export type Milestone = {source: Source; state: Status; revision: number | null; operation_id: string | null; occurred_at: string | null; amount_minor: number | null};
export type Timeline = {
  schema_version: 'order-timeline.v1'; order_id: string; watch_id: string; reference: string;
  revision: number; operation_id: string; currency: 'USD'; simulated: true; as_of: string;
  waiting: {party: Party; since: string; action: Action; operator_id: string; next_review_at: string; follow_up: 'scheduled' | 'due' | 'escalated'};
  economics: {principal_minor: number; buyer_fee_minor: number; business_fee_minor: number; total_minor: number; quote_id: string; quote_revision: number};
  financial: Financial[]; milestones: Milestone[];
};
export type OrderPage = {schema_version: 'order-timeline-list.v1'; items: {order_id: string; reference: string}[]; total: number; offset: number; limit: number};
export const operations = {
  list: {method: 'GET', path: '/v1/order-timeline', permission: 'current_record_scope'},
  read: {method: 'GET', path: '/v1/order-timeline/{order_id}', permission: 'current_record_scope'},
} as const;

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const ref = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(value);
const integer = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const utc = (value: unknown): value is string => typeof value === 'string' && value.endsWith('Z') && Number.isFinite(Date.parse(value));
const oneOf = (value: unknown, options: readonly string[]) => typeof value === 'string' && options.includes(value);
const exact = (value: Record<string, unknown>, keys: string) => Object.keys(value).sort().join(',') === keys.split(',').sort().join(',');
const sources = ['orders','payments','inspection','custody','progress','settlement'] as const;
/** Reject malformed private responses before they reach a retained view. */
export function isTimeline(value: unknown): value is Timeline {
  if (!object(value) || !exact(value,'schema_version,order_id,watch_id,reference,revision,operation_id,currency,simulated,as_of,waiting,economics,milestones,financial') || value.schema_version !== 'order-timeline.v1' || !ref(value.order_id) || !ref(value.watch_id) || !ref(value.reference) || !ref(value.operation_id) || !integer(value.revision) || value.revision < 1 || value.currency !== 'USD' || value.simulated !== true || !utc(value.as_of)) return false;
  const e = value.economics, w = value.waiting, rows = value.milestones;
  if (!object(e) || !exact(e,'principal_minor,buyer_fee_minor,business_fee_minor,total_minor,quote_id,quote_revision') || !['principal_minor','buyer_fee_minor','business_fee_minor','total_minor'].every(key => integer(e[key])) || !ref(e.quote_id) || !integer(e.quote_revision) || e.quote_revision < 1) return false;
  if (Number(e.total_minor) !== Number(e.principal_minor) + Number(e.buyer_fee_minor) || Number(e.business_fee_minor) > Number(e.principal_minor)) return false;
  if (!object(w) || !exact(w,'party,since,action,operator_id,next_review_at,follow_up') || !oneOf(w.party,['buyer','seller','business','operator','authenticator']) || !oneOf(w.action,['pay','review','receive','inspect','work','reconcile','wait']) || !ref(w.operator_id) || !utc(w.since) || !utc(w.next_review_at) || !oneOf(w.follow_up,['scheduled','due','escalated'])) return false;
  if (!Array.isArray(value.financial) || value.financial.length > 100 || new Set(value.financial.map(row => object(row) ? row.operation_id : null)).size !== value.financial.length || !value.financial.every(isFinancial)) return false;
  return Array.isArray(rows) && rows.length === sources.length && rows.every((row,index) => {
    if (!object(row) || !exact(row,'source,state,revision,operation_id,occurred_at,amount_minor') || row.source !== sources[index] || !oneOf(row.state,['pending','confirmed','blocked','unavailable','not_applicable'])) return false;
    if (row.state === 'unavailable') return row.operation_id === null && row.revision === null && row.occurred_at === null && row.amount_minor === null;
    return ref(row.operation_id) && integer(row.revision) && row.revision > 0 && utc(row.occurred_at) && (row.amount_minor === null || integer(row.amount_minor));
  });
}
export function isOrderPage(value: unknown): value is OrderPage {
  if (!object(value) || !exact(value,'schema_version,items,total,offset,limit') || value.schema_version !== 'order-timeline-list.v1' || !integer(value.total) || !integer(value.offset) || !integer(value.limit) || value.limit < 1 || value.limit > 20 || !Array.isArray(value.items)) return false;
  return value.items.length === Math.min(value.limit,Math.max(0,value.total-value.offset)) && value.items.every(row => object(row) && exact(row,'order_id,reference') && ref(row.order_id) && ref(row.reference)) && new Set(value.items.map(row => row.order_id)).size === value.items.length;
}

export type AccessLease = {actor_id: string; organization_id: string | null; order_id: string; watch_id: string; access_revision: number; source_revisions: [Source, number][]};
export type SourceSnapshot = {schema_version: 'timeline-source.v1'; source: Source; operation_id: string; order_id: string; watch_id: string; revision: number; state: Exclude<Status,'unavailable'>; occurred_at: string; amount_minor: number | null; quote_id: string; quote_revision: number; financial?: Financial[]; reference?: string; currency?: 'USD'; economics?: Timeline['economics']; waiting?: Omit<Timeline['waiting'],'next_review_at'|'follow_up'> & {last_progress_at: string}};

export function isFinancial(row: unknown): row is Financial {
  return object(row) && exact(row,'kind,state,amount_minor,operation_id,revision,occurred_at,source') && oneOf(row.kind,['gross','collected_fee','refund','net','payout']) && oneOf(row.state,['pending','confirmed','blocked']) && integer(row.amount_minor) && ref(row.operation_id) && integer(row.revision) && row.revision > 0 && utc(row.occurred_at) && oneOf(row.source,['payments','settlement']);
}
