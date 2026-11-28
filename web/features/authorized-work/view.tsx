'use client';
import { useReducer, useState } from 'react';
import { Button, Card, Input, Textarea, State, Skeleton, Select, formatNumber } from '@beirut-time/ui/foundation';
import { PageHeader, PageFrame, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { WorkContext, WorkOperation } from '@contracts/contracts-service/authorized-work/v1';
import { usePageRead } from '@/lib/page-speed/read';
import { workRead, historyRead } from './read';
import { formReducer, initialForm, type Fields } from './form';
import { submitWithRecovery } from './recovery';
import en from './en.json';
import ar from './ar.json';

const path = '/api/web/v1/service-operations/internal/v1/authorized-work';
export default function AuthorizedWork() {
  const access = useAccessContext();
  return <WorkForm key={access.fingerprint ?? 'denied'} fingerprint={access.fingerprint}/>;
}
function WorkForm({ fingerprint }: { fingerprint: string | null }) {
  const locale = useLocale(); const t = locale === 'ar' ? ar : en;
  const [form, dispatch] = useReducer(formReducer,initialForm);
  const {job,selected,kind,note,nextActor,nextAction,line,part,quantity,disposition,before,after,beforeAt,afterAt,method} = form.fields;
  const attempt = form.attempt;
  const field = (key:keyof Fields,value:string)=>dispatch({type:'field',field:key,value});
  const [status, setStatus] = useState(''); const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WorkOperation | null>(null);
  const context = usePageRead(fingerprint && selected ? workRead(fingerprint,selected) : null);

  const [offset,setOffset] = useState(0);
  const history = usePageRead(fingerprint && selected ? historyRead(fingerprint,selected,offset) : null);
  const privateDenied = status === 'denied' || [context.error, history.error].some(isAccessDenied);
  const submit = async () => {
    if (!fingerprint || !context.data || privateDenied || busy) return;
    let submission = attempt;
    setBusy(true); setStatus('pending');
    try {
      if (!submission) {
        const fresh = await authenticatedRequest<WorkContext>(
          `${path}/subjects/${encodeURIComponent(selected)}`,{accessFingerprint:fingerprint});
        const c = context.data;
        if (['subject_id','watch_id','actor_id','organization_id','expected_revision','source_revision',
             'quote_id','quote_revision','policy_revision','responsible_actor_id'].some(key=>
               fresh[key as keyof WorkContext] !== c[key as keyof WorkContext])) {
          void context.refetch();
          setStatus('stale');
          return;
        }
        const operation = crypto.randomUUID(); const now = new Date(fresh.server_now);
        const readings = kind === 'progress' ? [
          {phase:'before',value:before,instant:beforeAt},
          {phase:'after',value:after,instant:afterAt},
        ].filter(row=>row.value!=='').map(row=>{
          if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?Z$/.test(row.instant) ||
              !Number.isFinite(Date.parse(row.instant)) || Date.parse(row.instant)>now.getTime()) {
            throw new RangeError('Invalid observation time');
          }
          return {phase:row.phase,seconds_per_day:Number(row.value),method,observed_at:new Date(row.instant).toISOString()};
        }) : [];
        submission = {operation,body:JSON.stringify({schema_version:'authorized-work.v1',operation_id:operation,
          subject_id:c.subject_id,watch_id:c.watch_id,actor_id:c.actor_id,organization_id:c.organization_id,
          expected_revision:c.expected_revision,source_revision:c.source_revision,quote_id:c.quote_id,
          quote_revision:c.quote_revision,policy_revision:c.policy_revision,kind,line_ids:kind==='progress'?[line]:[],
          parts:kind==='progress'&&part?[{line_id:line,reference:part,quantity:Number(quantity),disposition}]:[],
          readings,note,observed_at:now.toISOString(),next_actor:nextActor || c.responsible_actor_id,next_action:nextAction,
          next_review_at:new Date(now.getTime()+3600000).toISOString()})};
        dispatch({type:'prepare',attempt:submission});
      }
      const answer = await submitWithRecovery(submission,
        retained=>authenticatedRequest<WorkOperation>(`${path}/commands`,{method:'POST',accessFingerprint:fingerprint,
          headers:{'Content-Type':'application/json'},body:retained.body}),
        operation=>authenticatedRequest<WorkOperation>(`${path}/operations/${encodeURIComponent(operation)}`,{accessFingerprint:fingerprint}),
        error=>error instanceof ApiError && (error.status===401 || error.status===403 || error.status===422 || error.details.not_applied===true));
      setResult(answer); setStatus(answer.state);
      if (answer.state !== 'pending') { dispatch({type:'acknowledged',operation:answer.operation_id}); void context.refetch(); void history.refetch(); }
    } catch (error) {
      if (error instanceof RangeError) { setStatus('correction'); }
      else if (error instanceof ApiError && (error.status===422 || error.details.not_applied===true)) { if (submission) dispatch({type:'acknowledged',operation:submission.operation}); setStatus('correction'); void context.refetch(); }
      else setStatus(error instanceof ApiError && error.status===403?'denied':error instanceof ApiError && error.status===409?'stale':'unavailable');
    } finally { setBusy(false); }
  };
  return <PageFrame><PageHeader title={t.title} notice={<p>{t.notice}</p>}/><PageBody>
    {!fingerprint || privateDenied ? <State title={t.denied} body={t.notice} kind="error"/> : <Card>
      <Input id="work-job" label={t.job} value={job} onValueChange={value=>field('job',value.slice(0,36))} disabled={busy || Boolean(attempt)}/>
      <Button disabled={busy || Boolean(attempt)} onClick={()=>{field('selected',job);field('line','');setOffset(0);setResult(null);}}>{t.load}</Button>
      {context.isPending && selected && <Skeleton/>}
      {context.isError && <State title={t.unavailable} body={t.notice} kind="error"><Button onClick={()=>void context.refetch()}>{t.retry}</Button></State>}
      {!selected && <State title={t.empty} body={t.notice}/>}
      {context.data && !privateDenied && <fieldset disabled={busy || Boolean(attempt)}>
        <Select id="work-kind" label={t.kind} value={kind} onValueChange={value=>field('kind',value)} messages={t.select} options={['progress','material_change','loss','damage','waiting_parts','waiting_customer','declined_return'].map(value=>({value,label:String(t[value as keyof typeof t])}))}/>
        <Select id="work-line" label={t.line} value={line} onValueChange={value=>field('line',value)} messages={t.select} options={context.data.accepted_lines.map(row=>({value:row.id,label:row.label}))}/>
        {kind==='progress' && <>
          <Input id="work-part" label={t.part} value={part} onValueChange={value=>field('part',value.slice(0,160))}/>
          <Input id="work-quantity" label={t.quantity} type="number" min={1} max={1000} step={1} value={quantity} onValueChange={value=>field('quantity',value)}/>
          <Select id="work-disposition" label={t.disposition} value={disposition} onValueChange={value=>field('disposition',value)} messages={t.select} options={['installed','consumed','removed_return','unused_return'].map(value=>({value,label:String(t[value as keyof typeof t])}))}/>
          <Input id="work-before" label={t.before} type="number" min={-86400} max={86400} step={1} value={before} onValueChange={value=>field('before',value)}/>
          <Input id="work-before-at" label={t.beforeAt} value={beforeAt} onValueChange={value=>field('beforeAt',value)} placeholder="2026-11-17T12:00:00Z"/>
          <Input id="work-after" label={t.after} type="number" min={-86400} max={86400} step={1} value={after} onValueChange={value=>field('after',value)}/>
          <Input id="work-after-at" label={t.afterAt} value={afterAt} onValueChange={value=>field('afterAt',value)} placeholder="2026-11-17T12:00:00Z"/>
          <Input id="work-method" label={t.method} value={method} onValueChange={value=>field('method',value.slice(0,160))}/>
        </>}
        <Textarea id="work-note" label={t.note} value={note} onValueChange={value=>field('note',value.slice(0,2000))}/>
        <Input id="work-actor" label={t.nextActor} value={nextActor} onValueChange={value=>field('nextActor',value.slice(0,36))}/>
        <Textarea id="work-next" label={t.nextAction} value={nextAction} onValueChange={value=>field('nextAction',value.slice(0,500))}/>
      </fieldset>}
      {context.data && !privateDenied && <Button disabled={busy || !note.trim() || !nextAction.trim() || (kind==='progress'&&!line)} onClick={()=>void submit()}>{attempt?t.retry:t.save}</Button>}
      {status && <State title={String(t[status as keyof typeof t] ?? t.unavailable)} body={t.notice} kind={status==='pending'?'loading':status==='recorded'||status==='paused'?'empty':'error'}/>}
      {!privateDenied && (result || attempt) && <p className="bt-text"><bdi>{attempt?.operation ?? result?.operation_id}</bdi></p>}
      {history.data && !privateDenied && <section aria-label={t.history}>
        <h2 className="bt-heading">{t.history} · {formatNumber(history.data.total,locale)}</h2>
        {history.data.items.length===0 && <State title={t.empty} body={t.notice}/>}
        {history.data.items.map(row=><Card key={row.operation_id}><p className="bt-text">{String(t[row.kind as keyof typeof t] ?? t.note)}</p><p className="bt-text">{row.note}</p><p className="bt-text">{row.next_action}</p><time dateTime={row.observed_at}>{new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(row.observed_at))}</time></Card>)}
        <Button disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-50))}>{t.previous}</Button>
        <Button disabled={history.data.next_offset===null} onClick={()=>setOffset(history.data?.next_offset ?? offset)}>{t.next}</Button>
      </section>}
      {history.isError && <State title={t.unavailable} body={t.notice} kind="error"><Button onClick={()=>void history.refetch()}>{t.retry}</Button></State>}
    </Card>}
  </PageBody></PageFrame>;
}

function isAccessDenied(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}
