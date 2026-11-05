'use client';
import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BidiReference, Button, Card, Input, RowSkeleton, Select, State, StatusBadge } from '@beirut-time/ui';
import { useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { displayMinor, minor } from '@/features/auction-management/api';
import { useOperationScope } from '@/features/auction-management/operation-scope';
import type { ConfigurePolicy, PolicySnapshot } from '@contracts/contracts-auction/policy';
import { readPolicy, savePolicy } from './api';
import en from './en.json';
import ar from './ar.json';
export function PolicyPanel({id,locale,editable=false,organization='',currency='USD'}:{id:string;locale:'en'|'ar';editable?:boolean;organization?:string;currency?:string}){
  const session=useSession();
  return <Panel key={`${id}:${organization}:${session?.access_fingerprint??'public'}`} id={id} locale={locale} editable={editable} organization={organization} currency={currency}/>;
}
function Panel({id,locale,editable,organization,currency}:{id:string;locale:'en'|'ar';editable:boolean;organization:string;currency:string}){
  const t=locale==='ar'?ar:en;const session=useSession();const scopeFor=useOperationScope();
  const policy=useQuery({queryKey:['auction-policy',id,session?.access_fingerprint,organization],queryFn:({signal})=>readPolicy(id,signal),retry:false,refetchInterval:5000});
  const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);const [uncertain,setUncertain]=useState(false);
  const [rule,setRule]=useState<ConfigurePolicy['extension_policy']|null>(null);const [price,setPrice]=useState<string|null>(null);
  const editRevision=useRef<number|null>(null);
  const inputPrice=(value:number|null)=>value===null?'':`${BigInt(value)/100n}.${String(BigInt(value)%100n).padStart(2,'0')}`;
  const attempt=useRef<{key:string;body:ConfigurePolicy;revision:number}|null>(null);
  async function save(event:React.FormEvent){event.preventDefault();if(!session||!policy.data||busy)return;const scope=scopeFor();setBusy(true);setMessage(t.saving);
    try{
      if(!attempt.current)attempt.current={key:crypto.randomUUID(),revision:editRevision.current??policy.data.revision,body:{extension_policy:rule??policy.data.extension_policy,buy_now_minor:price===null?policy.data.buy_now_minor:price?minor(price):null}};
      await savePolicy(id,attempt.current.body,attempt.current.revision,attempt.current.key,session.access_fingerprint,scope.controller.signal,organization);
      if(!scope.active)return;attempt.current=null;editRevision.current=null;setRule(null);setPrice(null);setUncertain(false);setMessage(t.saved);void policy.refetch();
    }catch(error){if(!scope.active)return;const unknown=!!attempt.current&&(!(error instanceof ApiError)||error.status>=500);setUncertain(unknown);if(!unknown)attempt.current=null;setMessage(error instanceof ApiError?(t[error.code as keyof typeof t]??(error.status===403?t.denied:t.unavailable)):t.invalid);}
    finally{if(scope.active)setBusy(false);}
  }
  if(policy.isPending)return <Card><RowSkeleton/><span role="status">{t.loading}</span></Card>;
  if(policy.isError)return <State kind="error" title={t.title} body={t.unavailable}><Button onClick={()=>policy.refetch()}>{t.retry}</Button></State>;
  const value=policy.data;
  return <Card className="auction-policy-panel"><PolicyFacts policy={value} locale={locale} currency={currency}/>
    {editable&&(!session?<p>{t.signedout}</p>:value.frozen?<p>{t.frozen}</p>:<form onSubmit={save} className="auction-policy-form"><fieldset disabled={busy||uncertain}>
      <label>{t.policy}<Select value={rule??value.extension_policy} aria-label={t.policy} onValueChange={next=>{editRevision.current??=value.revision;setRule(next as ConfigurePolicy['extension_policy']);}} options={[{value:'last-two-minutes.v1',label:t.twoMinutes},{value:'none.v1',label:t.noExtension}]}/></label>
      <label>{t.price}<Input value={price??inputPrice(value.buy_now_minor)} onChange={event=>{editRevision.current??=value.revision;setPrice(event.target.value);}} inputMode="decimal" autoComplete="off"/></label></fieldset>
      <Button type="submit" disabled={busy}>{uncertain?t.retry:t.save}</Button><Button type="button" variant="outline" disabled={busy||uncertain} onClick={()=>{editRevision.current=null;setRule(null);setPrice(null);setMessage('');void policy.refetch();}}>{t.retry}</Button></form>)}
    <p role="status" aria-live="polite">{message}</p>
  </Card>;
}
export function PolicyFacts({policy,locale,currency}:{policy:PolicySnapshot;locale:'en'|'ar';currency:string}){const t=locale==='ar'?ar:en;return <>
  <div className="auction-policy-row"><h2>{t.title}</h2><StatusBadge hue={policy.frozen?'orange':'blue'}>{policy.frozen?t.frozen:t.editable}</StatusBadge></div>
  <p>{policy.reserve_set?t.reserve:t.noReserve}</p><p>{policy.extension_policy==='last-two-minutes.v1'?t.extension:t.none}</p><p className="muted">{t.boundary}</p>
  <dl><div><dt>{t.ends}</dt><dd><BidiReference>{policy.current_ends_at}</BidiReference></dd></div><div><dt>{t.version}</dt><dd><BidiReference>{policy.end_version}</BidiReference></dd></div></dl>
  <p>{policy.buy_now_minor?`${t.buyNow}: ${displayMinor(policy.buy_now_minor,currency,locale)}`:t.disabled}</p>{policy.mode!=='bidding'&&<p role="status">{t.held}</p>}
</>;}
