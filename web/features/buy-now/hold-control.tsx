'use client';
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {Button,Card,Input} from '@beirut-time/ui';
import {useLocale} from '@/shell/locale-context';
import {authenticatedRequest} from '@/features/identity/session';
import {ApiError} from '@/lib/api/client';
import type {AllocationOperation,Order} from '@contracts/contracts-orders/allocation';
import {copy,errorText,requireAcknowledgedOperation} from './copy';

export default function HoldControl({record,onRefresh}:{record:Order;onRefresh:()=>void}){
  const t=copy(useLocale()),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState<unknown>(null),[saved,setSaved]=useState(false);
  const operation=useRef<{key:string;body:string}|null>(null),alive=useRef(true);
  useEffect(()=>{alive.current=true;const revoke=()=>{alive.current=false;};window.addEventListener('bt:access-change',revoke);return()=>{alive.current=false;window.removeEventListener('bt:access-change',revoke);};},[]);
  useEffect(()=>{
    const retain=(event:MouseEvent)=>{if((busy||uncertain)&&event.target instanceof Element&&event.target.closest('a.locale-control')){event.preventDefault();event.stopPropagation();}};
    document.addEventListener('click',retain,true);return()=>document.removeEventListener('click',retain,true);
  },[busy,uncertain]);
  async function hold(event:FormEvent){
    event.preventDefault();if(!alive.current)return;setBusy(true);setError(null);setSaved(false);
    operation.current??={key:crypto.randomUUID(),body:JSON.stringify({state:'payment_unknown',expected_revision:record.revision,reason:reason.trim()})};
    try{
      const scope=record.organization_id?'?organization_id='+encodeURIComponent(record.organization_id):'';
      const value=await authenticatedRequest<AllocationOperation>(`/api/web/v1/orders/v1/orders/${encodeURIComponent(record.id)}/transitions${scope}`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':operation.current.key},body:operation.current.body});
      requireAcknowledgedOperation(value);
      if(!alive.current)return;
      operation.current=null;setUncertain(false);setSaved(true);onRefresh();
    }catch(failure){if(alive.current){setError(failure);const unknown=!(failure instanceof ApiError)||failure.status>=500;setUncertain(unknown);if(!unknown)operation.current=null;if(failure instanceof ApiError&&failure.code==='stale_revision')onRefresh();}}
    finally{if(alive.current)setBusy(false);}
  }
  return <Card><h2>{t.hold}</h2><p>{t.holdHelp}</p><form className="checkout-form" method="post" autoComplete="off" onSubmit={hold}><label>{t.reason}<Input name="reason" value={reason} maxLength={200} required disabled={busy||uncertain} onChange={event=>setReason(event.target.value)}/></label><Button disabled={busy}>{busy?t.loading:uncertain?t.retry:t.hold}</Button>{!!error&&<p role="alert">{errorText(error,t)}</p>}{uncertain&&<p role="status">{t.uncertain}</p>}{saved&&<p role="status">{t.payment_unknown}</p>}</form></Card>;
}
