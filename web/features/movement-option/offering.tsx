'use client';
import { useEffect, useState } from 'react';
import { Button, Checkbox, Fold, Input, Select, State } from '@beirut-time/ui/foundation';
import { useSession } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import { movementPath, useCommandMutation, useJsonCommand } from '../service-directory/api';
import type { Movement } from '@contracts/contracts-service/directory';
import type { CompatibilityRule } from '@contracts/contracts-catalog/options/movement';
import en from './en.json';
import ar from './ar.json';
import { usePageRead } from '@/lib/page-speed/read';
import { definePageRead } from '@/lib/page-speed/definition';
import { useAccessContext } from '@/shell/access-context';
import { privateRequest } from '../service-directory/api';
import { privateReadDenied } from '../service-directory/private-read';
import { selectMessages } from '../service-directory/select-messages';
const offeringsRead=definePageRead({key:(fingerprint:string,brand:string,after:string|null)=>['movement-maintenance',fingerprint,brand,after],warm:'open-only',fresh:0,ask:(signal,fingerprint,brand,after)=>privateRequest<{items:(Movement&{active:boolean})[];next_after:string|null}>(`${movementPath}/maintenance/${brand}${after?`?after=${after}`:''}`,{signal,accessFingerprint:fingerprint})});
export function MovementOffering({brandId,selected,onSaved,onLockChange}:{brandId:string;selected?:(Movement&{active?:boolean});onSaved:()=>void;onLockChange?:(locked:boolean)=>void}) {
  const session=useSession(),locale=useLocale(),t=locale==='ar'?ar:en;
  const [locked,setLocked]=useState(false);
  const [open,setOpen]=useState(false),[create,setCreate]=useState(false);
  const access=useAccessContext();
  const [cursor,setCursor]=useState<string|null>(null),[optionId,setOptionId]=useState('');
  const permitted=session?.principal.organization_grants?.some(grant=>grant.organization_id===brandId&&grant.permissions.includes('business.stock.write'));
  const offerings=usePageRead(permitted&&access.fingerprint?offeringsRead(access.fingerprint,brandId,cursor):null);
  const denied=privateReadDenied(offerings.error);
  const [accessDenied,setAccessDenied]=useState(false);
  const restored=offerings.isSuccess&&!offerings.isFetching;
  if(denied&&!accessDenied)setAccessDenied(true);
  else if(accessDenied&&!denied&&restored)setAccessDenied(false);
  const blocked=denied||(accessDenied&&!restored);
  const current=blocked?undefined:(offerings.data?.items.find(item=>item.id===(optionId||selected?.id))??offerings.data?.items[0]);
  useEffect(()=>{onLockChange?.(locked);return()=>onLockChange?.(false);},[locked,onLockChange]);
  if(!permitted)return null;
  if(blocked)return <State kind="error" title={t.maintain} body={t.authDenied}><Button onClick={()=>void offerings.refetch()}>{t.retry}</Button></State>;
  return <Fold open={open} onOpenChange={setOpen} label={t.maintain}>
    <p className="bt-text">{t.offeringNotice}</p>
    {offerings.isError&&!offerings.data?<State kind="error" title={t.maintain} body={t.saveError}><Button onClick={()=>void offerings.refetch()}>{t.retry}</Button></State>:offerings.isPending&&open?<State kind="loading" title={t.maintain} body={t.loading}/>:<>
      <Select disabled={locked} label={t.option} value={current?.id??null} messages={selectMessages(locale)} onValueChange={setOptionId} options={(offerings.data?.items??[]).map(item=>({value:item.id,label:locale==='ar'?item.label_ar:item.label_en}))}/>
      {cursor&&<Button disabled={locked} type="button" onClick={()=>setCursor(null)}>{t.firstPage}</Button>}
      {offerings.data?.next_after&&<Button disabled={locked} type="button" onClick={()=>setCursor(offerings.data?.next_after??null)}>{t.more}</Button>}
      <Checkbox disabled={locked} label={t.newOption} checked={create} onCheckedChange={setCreate}/>
      <OfferingForm key={create?'new':current?.id??'first'} brandId={brandId} selected={create?undefined:current} onLock={setLocked} onSaved={()=>{void offerings.refetch();onSaved();}}/>
    </>}
    {offerings.isError&&offerings.data&&<State kind="error" title={t.maintain} body={t.saveError}><Button onClick={()=>void offerings.refetch()}>{t.retry}</Button></State>}
  </Fold>;
}
type RuleDraft = Omit<CompatibilityRule,'functions'> & {functions:string};
const ruleDrafts=(rules:CompatibilityRule[]):RuleDraft[]=>rules.map(rule=>({...rule,functions:rule.functions.join(', ')}));
export function OfferingForm({brandId,selected,onSaved,onLock}:{brandId:string;selected?:(Movement&{active?:boolean});onSaved:()=>void;onLock:(locked:boolean)=>void}) {
  const locale=useLocale(),t=locale==='ar'?ar:en,command=useJsonCommand();
  const [revision,setRevision]=useState(selected?.revision??0);
  const stale=revision!==(selected?.revision??0);
  const [identifier]=useState(()=>selected?.id??crypto.randomUUID());
  const [fields,setFields]=useState({label_en:selected?.label_en??'',label_ar:selected?.label_ar??'',caliber:selected?.caliber??'',cases:selected?.cases.join(', ')??'',dials:selected?.dials.join(', ')??'',hands:selected?.hands.join(', ')??'',functions:selected?.functions.join(', ')??'',dollars:selected?`${Math.floor(selected.quote_minor/100)}.${String(selected.quote_minor%100).padStart(2,'0')}`:''});
  const [rules,setRules]=useState<RuleDraft[]>(ruleDrafts(selected?.compatibility_rules??[]));
  const [active,setActive]=useState(selected?.active??true);
  const save=useCommandMutation({mutationFn:async()=>{
    const quote=usdCents(fields.dollars);
    const list=(value:string)=>value.split(/[,،]/).map(item=>item.trim()).filter(Boolean);
    const compatibility_rules=rules.map(rule=>({...rule,functions:list(rule.functions)}));
    return command(`${movementPath}/${identifier}`,{brand_id:brandId,expected_revision:revision,label_en:fields.label_en,label_ar:fields.label_ar,caliber:fields.caliber,cases:list(fields.cases),dials:list(fields.dials),hands:list(fields.hands),functions:list(fields.functions),quote_minor:quote,currency:'USD',active,compatibility_rules},'PUT');
  },onSuccess:onSaved});
  useEffect(()=>{onLock(save.isPending||save.needsRecovery);return()=>onLock(false);},[save.isPending,save.needsRecovery,onLock]);
  return <form className="movement-panel" onSubmit={event=>{event.preventDefault();if(!stale||save.needsRecovery)save.mutate();}}>
    {(['label_en','label_ar','caliber','cases','dials','hands','functions','dollars'] as const).map(field=><Input key={field} label={t[field]} value={fields[field]} required={field!=='functions'} disabled={save.isPending||save.needsRecovery} inputMode={field==='dollars'?'decimal':'text'} onValueChange={value=>setFields({...fields,[field]:value})}/>)}
    <p className="bt-text">{t.rulesHint}</p>
    {rules.map((rule,index)=><fieldset key={index}><legend>{t.rules}</legend>
      {(['case','dial','hands'] as const).map(field=><Input key={field} label={t[field]} required value={rule[field]} disabled={save.isPending||save.needsRecovery} onValueChange={value=>setRules(rows=>rows.map((row,i)=>i===index?{...row,[field]:value}:row))}/>)}
      <Input label={t.functions} value={rule.functions} disabled={save.isPending||save.needsRecovery} onValueChange={value=>setRules(rows=>rows.map((row,i)=>i===index?{...row,functions:value}:row))}/>
      <Select label={t.ruleState} value={rule.state} disabled={save.isPending||save.needsRecovery} messages={selectMessages(locale)} onValueChange={value=>setRules(rows=>rows.map((row,i)=>i===index?{...row,state:value as CompatibilityRule['state']}:row))} options={(['supported_for_review','incompatible','parts_unavailable'] as const).map(value=>({value,label:t[value==='supported_for_review'?'ruleSupported':value==='incompatible'?'ruleIncompatible':'rulePartsUnavailable']}))}/>
      <Button type="button" variant="outline" disabled={save.isPending||save.needsRecovery} onClick={()=>setRules(rows=>rows.filter((_,i)=>i!==index))}>{t.removeRule}</Button>
    </fieldset>)}
    <Button type="button" variant="outline" disabled={save.isPending||save.needsRecovery||rules.length>=100} onClick={()=>setRules(rows=>[...rows,{case:'',dial:'',hands:'',functions:'',state:'supported_for_review'}])}>{t.addRule}</Button>
    <Checkbox label={t.active} checked={active} disabled={save.isPending||save.needsRecovery} onCheckedChange={setActive}/>
    {stale&&<p role="alert">{t.stale}</p>}
    {stale&&<Button type="button" disabled={save.isPending||save.needsRecovery} onClick={()=>{
      setRevision(selected?.revision??0);
      setFields({label_en:selected?.label_en??'',label_ar:selected?.label_ar??'',caliber:selected?.caliber??'',cases:selected?.cases.join(', ')??'',dials:selected?.dials.join(', ')??'',hands:selected?.hands.join(', ')??'',functions:selected?.functions.join(', ')??'',dollars:selected?`${Math.floor(selected.quote_minor/100)}.${String(selected.quote_minor%100).padStart(2,'0')}`:''});
      setRules(ruleDrafts(selected?.compatibility_rules??[]));setActive(selected?.active??true);
    }}>{t.retry}</Button>}
    {save.isError&&<p role="alert">{t.saveError}</p>}{save.isSuccess&&<p role="status">{t.offeringSaved}</p>}
    <Button type="submit" disabled={save.isPending||(stale&&!save.needsRecovery)} aria-busy={save.isPending}>{save.isPending?t.saving:save.needsRecovery?t.retryOriginal:t.saveOffering}</Button>
  </form>;
}
export function usdCents(text:string):number {
  const normalized=text.trim().replace(/[٠-٩]/g,digit=>String(digit.charCodeAt(0)-0x660)).replace('٫','.');
  if(!/^\d{1,10}(?:\.\d{1,2})?$/.test(normalized))throw new RangeError('Enter an exact dollar amount');
  const [whole,fraction='']=normalized.split('.');
  const amount=Number(whole)*100+Number(fraction.padEnd(2,'0'));
  if(amount>999999999999)throw new RangeError('Dollar amount is too large');
  return amount;
}
