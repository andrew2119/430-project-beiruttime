'use client';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button, Card, Input, Select, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { useSession, useSessionState, refreshSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { FitCommand, FitContext } from '@contracts/contracts-service/fit-measurement/v1';
import { contextRead, saveMeasurement, type Scope } from './api';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { copy } from './copy';
import { createReadFence, millimeters, refreshedStatus, type MeasurementStatus } from './model';

export default function FitMeasurement() {
  useSession();
  const access=useAccessContext();
  const sessionState=useSessionState();
  const params=useSearchParams();
  const scope={subject_id:params.get('subject_id')??'',watch_id:params.get('watch_id')??'',organization_id:params.get('organization_id')??''};
  return <MeasurementForm key={`${access.fingerprint}:${scope.subject_id}:${scope.watch_id}:${scope.organization_id}`} scope={scope} access={access.fingerprint} sessionState={sessionState}/>;
}
type FormProps={scope:Scope;access:string|null;sessionState:ReturnType<typeof useSessionState>};
const hasScope=(scope:Scope)=>Object.values(scope).every(value=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value));

export function MeasurementForm(props:FormProps) {
  const t=copy[useLocale()];
  if(!props.access||!hasScope(props.scope)) {
    return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
      {!props.access?(props.sessionState==='restoring'?<PageLoading label={t.loading}/>:<State kind="error" title={props.sessionState==='unavailable'?t.unavailable:t.denied} body={t.intro}>{props.sessionState==='unavailable'?<Button onClick={()=>void refreshSession().catch(()=>{})}>{t.reload}</Button>:null}</State>):<State title={t.scope} body={t.intro}/>}
    </PageBody></PageFrame>;
  }
  return <ScopedMeasurementForm scope={props.scope} access={props.access}/>;
}

function ScopedMeasurementForm({scope,access}:{scope:Scope;access:string}) {
  const locale=useLocale(), t=copy[locale];
  const [readFence]=useState(createReadFence);
  const query=usePageRead(contextRead(scope,access));
  const [context,setContext]=useState<FitContext|null>(()=>query.data??null);
  const [size,setSize]=useState('');
  const [unit,setUnit]=useState<'cm'|'mm'>('cm');
  const [method,setMethod]=useState<FitCommand['method']>('tape');
  const [target,setTarget]=useState<FitCommand['target']>('comfortable');
  const [status,setStatus]=useState<MeasurementStatus>(()=>query.data?'ready':'loading');
  const attempt=useRef<FitCommand|null>(null);
  const [reference,setReference]=useState<string|null>(null);
  const inFlight=useRef(false);
  const active=useRef<AbortController|null>(null);
  const subject=scope.subject_id, watch=scope.watch_id, organization=scope.organization_id;
  const [observed,setObserved]=useState<{data:FitContext|undefined;error:unknown}>({data:undefined,error:null});
  if(readFence.accepts()&&status!=='denied'&&!query.isFetching&&(observed.data!==query.data||observed.error!==query.error)) {
    setObserved({data:query.data,error:query.error});
    if(query.isError) {
      const error=query.error;
      const denied=error instanceof ApiError&&(error.status===401||error.status===403);
      if(denied) {readFence.revoke();setContext(null);setSize('');setReference(null);}
      setStatus(current=>refreshedStatus(current,denied?'denied':'unavailable'));
    } else if(query.data && !query.isFetching) {
      setContext(query.data);
      setStatus(current=>refreshedStatus(current,'verified'));
    }
  }
  useEffect(()=>{
    const clear=()=>{readFence.revoke();active.current?.abort();attempt.current=null;setReference(null);setContext(null);setSize('');setStatus('denied');};
    window.addEventListener('bt:access-change',clear);
    return ()=>{active.current?.abort();window.removeEventListener('bt:access-change',clear);};
  },[access,subject,watch,organization,readFence]);
  useEffect(()=>{if(status==='denied') {active.current?.abort();attempt.current=null;}},[status]);
  const submit=async()=>{
    if(!readFence.accepts()||!access||!context||inFlight.current||(!attempt.current&&(query.isFetching||query.isError))) return;
    if(!attempt.current) {
      if(millimeters(size,unit)===null) {setStatus('invalid');return;}
      attempt.current={schema_version:'fit-measurement.v1',operation_id:crypto.randomUUID(),...scope,source_revision:context.source_revision,expected_revision:context.record?.revision??0,circumference:size,unit,method,source:'buyer_measured',target,final_fit_pass:false};
    }
    setReference(attempt.current.operation_id);
    const controller=new AbortController();active.current=controller;inFlight.current=true;setStatus('saving');
    try {
      const record=await saveMeasurement(attempt.current,access,controller.signal);
      if(controller.signal.aborted||!readFence.accepts()) return;
      setContext({...context,record});attempt.current=null;setStatus('saved');
    } catch(error) {
      if(controller.signal.aborted||!readFence.accepts()) return;
      if(error instanceof ApiError&&error.status<500) {
        if(error.status===401||error.status===403) {readFence.revoke();setContext(null);setSize('');setReference(null);}
        attempt.current=null;
        setStatus(error.status===401||error.status===403?'denied':error.status===409?'stale':error.status===422?'invalid':'error');
      } else setStatus('pending');
    } finally {inFlight.current=false;}
  };
  const locked=query.isFetching||query.isError||status==='saving'||status==='pending'||status==='denied'||status==='stale'||status==='unavailable'||status==='loading';
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    {status==='loading'?<PageLoading label={t.loading}/>:<AnswerArrival view="fit-measurement"><Card>
      {status!=='denied'&&readFence.accepts()&&context&&<>
        <p>{t.source}</p>
        <p>{context.record?<>{t.recorded}: <bdi dir="ltr">{formatNumber(context.record.circumference_mm,locale)} {t.mm}</bdi></>:t.empty}</p>
        {context.record&&<dl><dt>{t.method}</dt><dd>{context.record.method==='tape'?t.tape:t.string}</dd><dt>{t.target}</dt><dd>{context.record.target==='close'?t.close:context.record.target==='loose'?t.loose:t.comfortable}</dd></dl>}
        <form onSubmit={event=>{event.preventDefault();void submit();}}>
          <Input className="fit-measurement-size" label={t.size} hint={t.hint} value={size} onValueChange={setSize} disabled={locked} inputMode="decimal" required error={status==='invalid'?t.invalid:undefined}/>
          <Select label={t.unit} value={unit} onValueChange={value=>setUnit(value as typeof unit)} disabled={locked} messages={t.select} options={[{value:'cm',label:t.cm},{value:'mm',label:t.mm}]}/>
          <Select label={t.method} value={method} onValueChange={value=>setMethod(value as typeof method)} disabled={locked} messages={t.select} options={[{value:'tape',label:t.tape},{value:'string_and_ruler',label:t.string}]}/>
          <Select label={t.target} value={target} onValueChange={value=>setTarget(value as typeof target)} disabled={locked} messages={t.select} options={[{value:'close',label:t.close},{value:'comfortable',label:t.comfortable},{value:'loose',label:t.loose}]}/>
          <Button type="submit" disabled={locked} aria-busy={status==='saving'}>{t.save}</Button>
        </form>
      </>}
      {status!=='ready'&&status!=='invalid'&&<State body={t.intro} kind={status==='saved'?'empty':status==='saving'||status==='pending'?'loading':'error'} title={status==='saved'?t.saved:status==='saving'?t.saving:status==='pending'?t.pending:status==='denied'?t.denied:status==='stale'?t.stale:status==='unavailable'?t.unavailable:t.error}/>}
      {reference&&<p>{t.reference}: <bdi dir="ltr">{reference}</bdi></p>}
      {status==='pending'&&<Button onClick={()=>void submit()}>{t.retry}</Button>}
      {['unavailable','stale','error'].includes(status)&&<Button onClick={()=>{if(!context) setStatus('loading');void query.refetch();}}>{t.reload}</Button>}
    </Card></AnswerArrival>}
  </PageBody></PageFrame>;
}
