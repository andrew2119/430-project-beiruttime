import {readNonSecretDraft,saveNonSecretDraft} from '@/shell/private-state';
import {uuid} from './copy';
export type QuoteSelection={owner:string;listingId:string;quoteId:string};
const key='checkout-quote';
export function readQuoteSelection(owner:string):QuoteSelection|null{
  try{const v=JSON.parse(readNonSecretDraft(owner,key)??'null');if(v?.owner===owner&&uuid.test(v.listingId)&&uuid.test(v.quoteId))return v;}catch{/* Storage is optional. */}return null;
}
export function rememberQuoteSelection(value:QuoteSelection){try{saveNonSecretDraft(value.owner,key,JSON.stringify(value));}catch{/* Pricing remains authoritative. */}}
export function clearQuoteSelection(owner:string){try{saveNonSecretDraft(owner,key,'null');}catch{}}
