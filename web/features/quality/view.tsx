'use client';
import { useRef, useState } from 'react';
import { Button, Card, Select, State, Textarea, formatNumber } from '@beirut-time/ui/foundation';
import type { QualityCommand, QualityReceipt } from '@contracts/contracts-service/quality/v1';
import { PageHeader, PageFrame } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { blank, complete, fields, makeCommand, validContext, type Context } from './draft';
import { messages } from './messages';

export type QualityPorts = {
  context?: Context; state: 'ready' | 'loading' | 'empty' | 'denied' | 'unavailable';
  submit: (command: QualityCommand)=>Promise<QualityReceipt | {state:'pending'} | {state:'denied'|'stale'|'unavailable'|'rejected'}>;
  reload: ()=>void;
  readPage?: (offset: number, limit: number) => Promise<Context>;
};
function canonicalBinding(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right))) : item);
}
export default function QualityView(props: QualityPorts) {
  const access = useAccessContext();
  const [retained, setRetained] = useState({ fingerprint: access.fingerprint, context: props.context });
  const context = props.state === 'denied' ? undefined : props.context ?? ((props.state === 'loading' || props.state === 'unavailable') && retained.fingerprint === access.fingerprint ? retained.context : undefined);
  if (retained.fingerprint !== access.fingerprint || retained.context !== context) {
    setRetained({ fingerprint: access.fingerprint, context });
  }
  const binding = context ? canonicalBinding(context) : '';
  return <QualityContent key={`${access.fingerprint}:${binding}:${props.state === 'denied'}`} context={context} state={props.state} submit={props.submit} reload={props.reload} readPage={props.readPage}/>;
}
function QualityContent({context,state,submit,reload,readPage}: QualityPorts) {
  const locale = useLocale();
  const t = messages[locale];
  const [lines,setLines] = useState(()=>context?.line_ids.map(id=>blank(id,context.test_keys[id])) ?? []);
  const [page,setPage] = useState(0);
  const [pages,setPages] = useState<Record<number, Context>>((): Record<number, Context>=>context ? {0:context} : {});
  const [pageBusy,setPageBusy] = useState(false);
  const [pageError,setPageError] = useState(false);
  const total = context?.total ?? context?.line_ids.length ?? 0;
  const serverPaging = context?.total !== undefined;
  const visibleIds = serverPaging ? pages[page]?.line_ids ?? [] : lines.slice(page*5,page*5+5).map(line=>line.line_id);
  const allComplete = lines.length === total && complete(lines);
  async function changePage(next: number) {
    if (pageBusy || state !== 'ready') return;
    if (!serverPaging || pages[next]) { setPage(next); return; }
    if (!readPage || !context) { setPageError(true); return; }
    setPageBusy(true); setPageError(false);
    try {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const result = await Promise.race([readPage(next*5,5), new Promise<never>((_,reject)=>{
        timer = setTimeout(()=>reject(new Error('page_timeout')),1200);
      })]).finally(()=>clearTimeout(timer));
      const {line_ids: initialIds, test_keys: initialKeys, total: initialTotal, ...initialBinding} = context;
      const {line_ids, test_keys, total: receivedTotal, ...receivedBinding} = result;
      void initialIds; void initialKeys; void initialTotal;
      if (!validContext(result) || receivedTotal !== total || total > 1000 || line_ids.length !== Math.min(5,total-next*5)
          || canonicalBinding(initialBinding) !== canonicalBinding(receivedBinding)
          || line_ids.some(id=>lines.some(line=>line.line_id===id))) throw new Error('stale_page');
      setPages(old=>({...old,[next]:result}));
      setLines(old=>[...old,...line_ids.map(id=>blank(id,test_keys[id]))]);
      setPage(next);
    } catch { setPageError(true); }
    finally { setPageBusy(false); }
  }
  const [status,setStatus] = useState<'idle'|'pending'|'satisfactory'|'rework'|'denied'|'stale'|'unavailable'|'rejected'>('idle');
  const [busy,setBusy] = useState(false);
  const [operationId,setOperationId] = useState('');
  const [retryReady,setRetryReady] = useState(true);
  const [previousState,setPreviousState] = useState(state);
  if (previousState !== state) {
    setPreviousState(state);
    if (state === 'ready') setRetryReady(true);
  }
  const inFlight = useRef(false);
  const operation = useRef<QualityCommand | null>(null);
  const locked = pageBusy || state !== 'ready' || (status !== 'idle' && status !== 'rejected');
  async function save() {
    if ((status === 'unavailable' && !retryReady) || inFlight.current || state !== 'ready' || !context || !validContext(context) || !allComplete) return;
    inFlight.current = true;
    operation.current ??= makeCommand(serverPaging ? {...context,line_ids:lines.map(line=>line.line_id),test_keys:Object.assign({},...Object.values(pages).map(item=>item.test_keys))} : context,lines,crypto.randomUUID());
    setOperationId(operation.current.operation_id);
    setBusy(true); setStatus('pending');
    try {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const result = await Promise.race([submit(operation.current), new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('submission_timeout')), 1200);
      })]).finally(() => clearTimeout(timer));
      if (result.state === 'denied') {
        setLines([]);
        setPage(0);
        operation.current = null;
        setOperationId('');
      }
      if (result.state === 'rejected') {
        operation.current = null;
        setOperationId('');
      }
      if (result.state === 'unavailable') setRetryReady(false);
      setStatus(result.state);
    } catch { setStatus('pending'); }
    finally { inFlight.current = false; setBusy(false); }
  }
  return <PageFrame><PageHeader title={t.title} count={t.intro}/>
    {(state !== 'ready' || !context || !validContext(context)) && <State title={t.title} kind={state==='loading'?'loading':state==='denied'?'error':'empty'} body={t[state==='ready'?'unavailable':state]}>
      {state!=='loading'&&<Button onClick={reload}>{t.retry}</Button>}
    </State>}
    {status === 'denied' && <State title={t.title} kind="error" body={t.denied}>
      <Button onClick={reload}>{t.reload}</Button>
    </State>}
    {status !== 'denied' && context && validContext(context) && <form aria-busy={state !== 'ready' || pageBusy} onSubmit={event=>{event.preventDefault();void save();}}>
      <p>{t.actual}</p>
      {visibleIds.map(id=>lines.find(line=>line.line_id===id)!).map((line)=><Card key={line.line_id}>
        <h2><bdi>{line.line_id}</bdi></h2>
        {Object.entries(line.tests).map(([key,entry])=><div key={key}>
          <Textarea label={`${t.tests} · ${key}`} value={entry.actual} required disabled={locked} onValueChange={actual=>setLines(old=>old.map((item)=>item.line_id===line.line_id?{...item,tests:{...item.tests,[key]:{...entry,actual}}}:item))}/>
          <Select label={`${key} · ${t.result}`} value={entry.result} disabled={locked}
            onValueChange={result=>setLines(old=>old.map((item)=>item.line_id===line.line_id?{...item,tests:{...item.tests,[key]:{...entry,result:result as 'pass'|'fail'}}}:item))}
            options={[{value:'pass',label:t.pass},{value:'fail',label:t.fail}]}
            messages={{placeholder:t.choose,filter:t.result,emptyTitle:t.empty,emptyBody:t.empty,close:t.save,loading:t.loading,errorTitle:t.unavailable,errorBody:t.unavailable,retry:t.retry}}/>
        </div>)}
        {fields.map(field=><div key={field}>
          <Textarea label={t[field]} value={line[field].actual} required disabled={locked} onValueChange={actual=>setLines(old=>old.map((item)=>item.line_id===line.line_id?{...item,[field]:{...item[field],actual}}:item))}/>
          <Select label={`${t[field]} · ${t.result}`} value={line[field].result} disabled={locked}
            onValueChange={result=>setLines(old=>old.map((item)=>item.line_id===line.line_id?{...item,[field]:{...item[field],result:result as 'pass'|'fail'}}:item))}
            options={[{value:'pass',label:t.pass},{value:'fail',label:t.fail}]}
            messages={{placeholder:t.choose,filter:t.result,emptyTitle:t.empty,emptyBody:t.empty,close:t.save,loading:t.loading,errorTitle:t.unavailable,errorBody:t.unavailable,retry:t.retry}}/>
        </div>)}
      </Card>)}
      <p>{formatNumber(Math.min(page*5+visibleIds.length,total),locale)} / {formatNumber(total,locale)}</p>
      <Button type="button" disabled={state!=='ready'||pageBusy||page===0} onClick={()=>void changePage(page-1)}>{t.previous}</Button>
      <Button type="button" disabled={state!=='ready'||pageBusy||(page+1)*5>=total} onClick={()=>void changePage(page+1)}>{t.next}</Button>
      {pageError&&<State title={t.title} body={t.unavailable} kind="error"><Button type="button" onClick={()=>void changePage(page+1)}>{t.retry}</Button></State>}
      {status!=='idle'&&<State title={t.title} body={t[status]} kind={status==='pending'?'loading':status==='rejected'?'error':'empty'}/>}
      {operationId&&<p>{t.operation}: <bdi>{operationId}</bdi></p>}
      {['rework','denied','stale','unavailable'].includes(status)&&<Button type="button" onClick={reload}>{t.reload}</Button>}
      <Button type="submit" disabled={(status==='unavailable'&&!retryReady)||state!=='ready'||busy||!allComplete||(status!=='idle'&&status!=='pending'&&status!=='unavailable'&&status!=='rejected')} aria-busy={busy}>{status==='pending'||status==='unavailable'?t.retry:t.save}</Button>
    </form>}
  </PageFrame>;
}
