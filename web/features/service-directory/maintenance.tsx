'use client';
import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Checkbox, Input, Textarea, Select, State } from '@beirut-time/ui/foundation';
import { definePageRead } from '@/lib/page-speed/definition';
import { usePageRead } from '@/lib/page-speed/read';
import { useSession } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import type { Business, Capability } from '@contracts/contracts-service/directory';
import { directoryPath, privateRequest, useCommandMutation, useJsonCommand } from './api';
import { selectMessages } from './select-messages';
import { privateReadDenied } from './private-read';
import en from './en.json';
import ar from './ar.json';
const maintenanceRead=definePageRead({key:(fingerprint:string,id:string)=>['directory-maintenance',fingerprint,id],warm:'open-only',fresh:0,ask:(signal,fingerprint,id)=>privateRequest<{profile:(Business&{published:boolean})|null}>(`${directoryPath}/maintenance/${id}`,{signal,accessFingerprint:fingerprint})});
const capabilities:Capability[]=['maintenance','cleaning','polishing','repair','bracelet_fit','customization'];
type Draft={expected_revision:number;contact:string;visit_en:string;visit_ar:string;scope_en:string;scope_ar:string;capabilities:Capability[];published:boolean};
export function OfferingMaintenance({onLockChange}:{onLockChange?:(locked:boolean)=>void}) {
  const session=useSession(), access=useAccessContext(),locale=useLocale(),t=locale==='ar'?ar:en;
  const grants=session?.principal.organization_grants?.filter(grant=>grant.permissions.includes('business.jobs.write'))??[];
  const [business,setBusiness]=useState(''),[locked,setLocked]=useState(false);
  const lock=useCallback((value:boolean)=>{setLocked(value);onLockChange?.(value);},[onLockChange]);
  if(!grants.length)return null;
  const selected=grants.some(grant=>grant.organization_id===business)?business:grants[0].organization_id;
  return <Card className="directory-maintenance"><h2>{t.maintain}</h2><p className="bt-text">{t.maintenanceNotice}</p>
    <Select disabled={locked} label={t.business} value={selected} onValueChange={setBusiness} messages={selectMessages(locale)} options={grants.map(grant=>({value:grant.organization_id,label:grant.organization_id}))}/>
    <MaintenanceForm key={`${access.fingerprint}:${selected}`} business={selected} onLock={lock}/>
  </Card>;
}
export function MaintenanceForm({business,onLock}:{business:string;onLock:(locked:boolean)=>void}) {
  const access=useAccessContext(),locale=useLocale(),t=locale==='ar'?ar:en,command=useJsonCommand();
  const current=usePageRead(access.fingerprint?maintenanceRead(access.fingerprint,business):null);
  const [draft,setDraft]=useState<Draft|null>(null);
  const denied=privateReadDenied(current.error);
  const [accessDenied,setAccessDenied]=useState(false);
  const restored=current.isSuccess&&!current.isFetching;
  if(denied&&!accessDenied)setAccessDenied(true);
  else if(accessDenied&&!denied&&restored)setAccessDenied(false);
  const blocked=denied||(accessDenied&&!restored);
  if(blocked&&draft)setDraft(null);
  const profile=blocked?undefined:current.data?.profile;
  const value=draft??{expected_revision:profile?.revision??0,contact:profile?.contact??'',visit_en:profile?.visit_en??'',visit_ar:profile?.visit_ar??'',scope_en:profile?.scope_en??'',scope_ar:profile?.scope_ar??'',capabilities:profile?.capabilities??[],published:profile?.published??false};
  const save=useCommandMutation({mutationFn:()=>command(`${directoryPath}/businesses/${business}`,value,'PUT'),onSuccess:()=>{setDraft(null);void current.refetch();}});
  useEffect(()=>{onLock(save.isPending||save.needsRecovery);return()=>onLock(false);},[save.isPending,save.needsRecovery,onLock]);
  if(blocked)return <State kind="error" title={t.maintain} body={t.authDenied}><Button onClick={()=>void current.refetch()}>{t.retry}</Button></State>;
  if(current.isPending&&!current.data)return <State kind="loading" title={t.maintain} body={t.loading}/>;
  if(current.isError&&!current.data)return <State kind="error" title={t.maintain} body={t.authDenied}><Button onClick={()=>void current.refetch()}>{t.retry}</Button></State>;
  const stale=Boolean(draft&&draft.expected_revision!==(profile?.revision??0));
  return <form onSubmit={event=>{event.preventDefault();if(!stale||save.needsRecovery)save.mutate();}}>
    {(['contact','visit_en','visit_ar','scope_en','scope_ar'] as const).map(field=>field==='contact'?<Input key={field} label={t[field]} required value={value[field]} disabled={save.isPending||save.needsRecovery} onValueChange={text=>setDraft({...value,[field]:text})}/>:<Textarea key={field} label={t[field]} required value={value[field]} disabled={save.isPending||save.needsRecovery} onValueChange={text=>setDraft({...value,[field]:text})}/>)}
    {capabilities.filter(capability=>profile?.kind!=='dealer'||capability!=='customization').map(capability=><Checkbox key={capability} label={t[capability]} disabled={save.isPending||save.needsRecovery} checked={value.capabilities.includes(capability)} onCheckedChange={checked=>setDraft({...value,capabilities:checked?[...value.capabilities,capability]:value.capabilities.filter(item=>item!==capability)})}/>)}
    <Checkbox label={t.published} checked={value.published} disabled={save.isPending||save.needsRecovery} onCheckedChange={published=>setDraft({...value,published})}/>
    {current.isError&&<State kind="error" title={t.maintain} body={t.authUnavailable}/>}
    {stale&&<p role="alert">{t.stale}</p>}
    {save.isError&&<State kind="error" title={t.maintain} body={t.recover}/>}
    {save.isSuccess&&<p role="status">{t.profileSaved}</p>}
    <Button type="submit" disabled={save.isPending||!value.capabilities.length||(stale&&!save.needsRecovery)} aria-busy={save.isPending}>{save.isPending?t.saving:save.needsRecovery?t.retryOriginal:t.saveProfile}</Button>
    <Button type="button" variant="outline" disabled={save.isPending||save.needsRecovery} onClick={()=>{setDraft(null);void current.refetch();}}>{t.refresh}</Button>
  </form>;
}
