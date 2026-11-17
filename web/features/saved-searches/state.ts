import { normalizeDigits } from '@beirut-time/i18n';
import type { Command, Criteria, SavedSearch } from '@contracts/contracts-comms/saved-searches';
export type Draft = {importInvalid?:boolean;importedCurrency?:string;id:string|null;revision:number;name:string;q:string;brand:string;model:string;location:string;minimum:string;maximum:string;sale_mode:Criteria['sale_mode'];sort:Criteria['sort'];alerts:boolean};
export const emptyDraft:Draft = {id:null,revision:0,name:'',q:'',brand:'',model:'',location:'',minimum:'',maximum:'',sale_mode:'',sort:'newest',alerts:false};
export function dollars(value:string):number|null {
  const normalized = normalizeDigits(value).trim().replace('٫','.');
  if (!normalized) return null;
  if (!/^\d{1,14}(?:\.\d{1,2})?$/.test(normalized)) throw new Error('invalid_range');
  const [whole,fraction=''] = normalized.split('.');
  const minor = BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
  if (minor>9000000000000000n) throw new Error('invalid_range');
  return Number(minor);
}
export function amount(value:number|null):string {return value===null?'':`${Math.floor(value/100)}.${String(value%100).padStart(2,'0')}`;}
export function criteria(draft:Draft):Criteria {
  if(draft.importInvalid)throw new Error('invalid_filters');
  const min_minor=dollars(draft.minimum),max_minor=dollars(draft.maximum);
  if(min_minor!==null&&max_minor!==null&&min_minor>max_minor)throw new Error('invalid_range');
  if(!draft.name.trim()||draft.name.length>120||/[\u0000-\u001f]/.test(draft.name)||draft.q.length>160||draft.q.trim().split(/\s+/).filter(Boolean).length>8||draft.brand.length>100||draft.model.length>160||draft.location.length>160)throw new Error('invalid_filters');
  return {q:draft.q,brand:draft.brand,model:draft.model,location:draft.location,min_minor,max_minor,currency:'USD',sale_mode:draft.sale_mode,sort:draft.sort};
}
export function fromSaved(row:SavedSearch):Draft {return {id:row.id,revision:row.revision,name:row.name,q:row.criteria.q,brand:row.criteria.brand,model:row.criteria.model,location:row.criteria.location,minimum:amount(row.criteria.min_minor),maximum:amount(row.criteria.max_minor),sale_mode:row.criteria.sale_mode,sort:row.criteria.sort,alerts:row.alerts_enabled};}
export function makeCommand(draft:Draft,kind:Command['kind']='save'):Command {return {schema_version:'saved-searches.v1',operation_id:crypto.randomUUID(),subject_id:draft.id??crypto.randomUUID(),expected_revision:draft.revision,kind,name:draft.name,criteria:criteria(draft),alerts_enabled:draft.alerts};}
// Presentation language is deliberately absent from the immutable operation.
export function searchHref(value:Criteria):string {const params=new URLSearchParams();for(const [key,item]of Object.entries(value))if(item!==null&&item!=='')params.set(key,String(item));return `/search?${params}`;}
export function fromQuery(params:URLSearchParams):Draft {
  const draft={...emptyDraft};
  for(const field of ['q','brand','model','location'] as const)draft[field]=params.get(field)??'';
  for(const [field,key]of [['minimum','min_minor'],['maximum','max_minor']] as const){
    const value=params.get(key);
    if(value!==null&&value!==''){
      if(!/^\d{1,16}$/.test(value)||BigInt(value)>9000000000000000n){draft[field]=value;draft.importInvalid=true;}
      else draft[field]=amount(Number(value));
    }
  }
  if(params.has('currency')&&params.get('currency')!=='USD')draft.importedCurrency=params.get('currency')!;
  const mode=params.get('sale_mode')??'',sort=params.get('sort')??'newest';
  if(!['','fixed','auction','offer'].includes(mode)||!['newest','price_asc','price_desc','ending_soon'].includes(sort)||(params.has('currency')&&params.get('currency')!=='USD'))draft.importInvalid=true;
  draft.sale_mode=mode as Draft['sale_mode'];draft.sort=sort as Draft['sort'];return draft;
}
