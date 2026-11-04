'use client';
import { readNonSecretDraft, saveNonSecretDraft } from '@/shell/private-state';

const kinds=['listing','user','message'];
const categories=['counterfeit','misleading','harassment','payment_abuse','other'];
const uuid=/^[0-9a-fA-F-]{36}$/;
function read(scope:string,key:string):Record<string,unknown> {
  try {const raw=readNonSecretDraft(scope,key);const value=raw?JSON.parse(raw):null;return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}catch{return {};}
}
function save(scope:string,key:string,value:Record<string,unknown>) {
  try {saveNonSecretDraft(scope,key,JSON.stringify(value));}catch{/* Revocation/storage refusal must not recreate prior-user state. */}
}

export function reportChoices(scope:string) {
  const value=read(scope,'moderation-choices');
  const target_kind=typeof value.target_kind==='string'&&kinds.includes(value.target_kind)?value.target_kind:'listing';
  const category=typeof value.category==='string'&&categories.includes(value.category)?value.category:'misleading';
  return {target_kind,category,target_id:target_kind==='listing'&&typeof value.target_id==='string'&&uuid.test(value.target_id)?value.target_id:''};
}
export function saveReportChoices(scope:string,value:{target_kind:string;category:string;target_id:string}) {
  // Public listing references and choice preferences only: never evidence or private message/account references.
  save(scope,'moderation-choices',{target_kind:value.target_kind,category:value.category,target_id:value.target_kind==='listing'?value.target_id:''});
}
export function organizationChoice(scope:string,organizations:string[]) {
  const value=read(scope,'intake-business').organization_id;
  return typeof value==='string'&&organizations.includes(value)?value:organizations.length===1?organizations[0]:'';
}
export function saveOrganizationChoice(scope:string,id:string) {save(scope,'intake-business',{organization_id:id});}
export function intakeSelection(scope:string,organization:string) {
  const value=read(scope,'intake-selection:'+organization).record_id;
  return typeof value==='string'&&uuid.test(value)?value:null;
}
export function saveIntakeSelection(scope:string,organization:string,id:string|null) {save(scope,'intake-selection:'+organization,{record_id:id});}
export function currencyChoice(scope:string):'USD'|'LBP' {return read(scope,'intake-currency').currency==='LBP'?'LBP':'USD';}
export function saveCurrencyChoice(scope:string,currency:'USD'|'LBP') {save(scope,'intake-currency',{currency});}
