'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, Card, State, Textarea, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { usePageRead } from '@/lib/page-speed/read';
import type { Command, Evidence, History, Review } from '@contracts/contracts-eligibility/private-review';
import { historyRead, readEvidence, reviewRead, sendCommand } from './api';
import { copy } from './copy';

export default function ReviewView({caseId}:{caseId?:string}) {
  const session = useSession(), locale = useLocale(), t = copy[locale];
  if (!session || !caseId) return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody><State title={t.unavailable} body={t.unavailableBody}/></PageBody></PageFrame>;
  return <Workspace key={`${session.access_fingerprint}:${caseId}`} access={session.access_fingerprint} caseId={caseId}/>;
}
function Workspace({access,caseId}:{access:string;caseId:string}) {
  const locale = useLocale(), t = copy[locale];
  const query = usePageRead(reviewRead(access,caseId));
  const [recovery,setRecovery] = useState(0);
  const [operation,setOperation] = useState<Command|null>(null);
  const [denied,setDenied] = useState(false), [page,setPage] = useState(1);
  const history = usePageRead(historyRead(access,caseId,query.data?.revision ?? 0,page));
  const historyDenied = history.error instanceof ApiError && [401,403,404].includes(history.error.status);
  const queryDenied = query.error instanceof ApiError && [401,403,404].includes(query.error.status);
  function clearAccess() {
    setOperation(null);setDenied(true);
  }
  if ((queryDenied || historyDenied) && !denied) clearAccess();
  async function reload() {
    const result = await query.refetch();
    const historyResult = denied ? await history.refetch() : null;
    if (!result.error && !historyResult?.error) {setRecovery(value=>value+1);setDenied(false);}
  }
  if (query.isPending) return <PageLoading label={t.loading}/>;
  // Never retain private content under a denied or uncertain fresh read.
  if (denied || query.error || !query.data) {
    const accessRemoved = denied || queryDenied;
    return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody><State kind="error" title={accessRemoved?t.denied:t.error} body={accessRemoved?t.deniedBody:t.errorBody}><Button onClick={()=>void reload()}>{t.retry}</Button></State></PageBody></PageFrame>;
  }
  return <ReviewForm key={`${caseId}:${query.data.assignment_revision}:${query.data.binding.source_revision}:${recovery}`} access={access} review={query.data} reload={reload} operation={operation} setOperation={setOperation} clearAccess={clearAccess} history={history} page={page} setPage={setPage}/>;
}
function ReviewForm({access,review,reload,operation,setOperation,clearAccess,history,page,setPage}:{
  access:string;review:Review;reload:()=>Promise<void>;operation:Command|null;
  setOperation:(value:Command|null)=>void;clearAccess:()=>void;
  history:ReturnType<typeof usePageRead<History>>;
  page:number;setPage:React.Dispatch<React.SetStateAction<number>>;
}) {
  const locale = useLocale(), t = copy[locale];
  const [reason,setReason] = useState('');
  const pending = operation !== null;
  const [evidence,setEvidence] = useState<Evidence|null>(null), [evidenceError,setEvidenceError] = useState(false);
  const [busy,setBusy] = useState(false), [denied,setDenied] = useState(false);
  const running = useRef(false), mounted = useRef(true);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
  const [failure,setFailure] = useState<'stale'|'invalid'|null>(null);
  async function submit(kind:Command['kind'], verdict?:Command['verdict']) {
    if (running.current || (!operation && !reason.trim())) return;
    running.current=true;setFailure(null);
    const action:Command = operation ?? {schema_version:'eligibility.private-review.v1',operation_id:crypto.randomUUID(),case_id:review.case_id,
      expected_revision:review.revision,assignment_revision:review.assignment_revision,binding:review.binding,kind,verdict,reason};
    setOperation(action);setBusy(true);
    try {
      await sendCommand(access,action);
      if (!mounted.current) return;
      setOperation(null);setReason('');setEvidence(null);await reload();
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ApiError && [401,403,404].includes(error.status)) {setDenied(true);clearAccess();}
      else if (error instanceof ApiError && [409,422].includes(error.status)) {
        setFailure(error.status===409?'stale':'invalid');setOperation(null);setEvidence(null);
      } else {setOperation(action);}
    } finally {running.current=false;setBusy(false);}
  }
  async function evidenceRead() {
    if (busy) return;
    setBusy(true);setEvidenceError(false);
    try {const value=await readEvidence(access,review.case_id);if (mounted.current) setEvidence(value);}
    catch (error) {if (!mounted.current) return;setEvidence(null);setEvidenceError(true);if (error instanceof ApiError && [401,403,404].includes(error.status)) {setDenied(true);clearAccess();}}
    finally {setBusy(false);}
  }
  if (denied) return <PageFrame><PageHeader title={t.title}/><PageBody><State kind="error" title={t.denied} body={t.deniedBody}><Button onClick={reload}>{t.refresh}</Button></State></PageBody></PageFrame>;
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    <Card><h2 className="bt-heading">{t[review.state]}</h2><p className="bt-text">{t.reference}: <bdi>{review.case_id}</bdi></p><p className="bt-text">{t.revision}: {formatNumber(review.revision,locale)}</p>
      <Button disabled={busy||pending} onClick={()=>void evidenceRead()}>{t.evidence}</Button>
      {evidence && <div role="status"><p>{t[evidence.identity_match]}</p><p>{evidence.document_valid?t.valid:t.invalid}</p></div>}
      {evidenceError && <State kind="error" title={t.noEvidence} body={t.errorBody}/>}
      <Textarea label={t.reason} hint={t.reasonHint} value={reason} onValueChange={setReason} disabled={busy||pending} required/>
      {failure && <State kind="error" title={failure==='stale'?t.changed:t.error} body={failure==='stale'?t.changedBody:t.invalidFields}><Button onClick={reload}>{t.refresh}</Button></State>}
      {pending ? <State kind="loading" title={t.pending} body={t.pendingBody}><bdi>{operation?.operation_id}</bdi><Button busy={busy} onClick={()=>void submit(operation!.kind,operation!.verdict)}>{t.retry}</Button></State> : <div>
        {['assigned','correction','invalidated'].includes(review.state) && <Button disabled={!reason.trim()||busy||failure==='stale'} onClick={()=>void submit('claim')}>{t.claim}</Button>}
        {review.state==='under_review' && <><Button disabled={!reason.trim()||busy||failure==='stale'} onClick={()=>void submit('correct')}>{t.correct}</Button><Button disabled={!reason.trim()||busy||failure==='stale'||!evidence} onClick={()=>void submit('decide','eligible')}>{t.eligible}</Button><Button disabled={!reason.trim()||busy||failure==='stale'||!evidence} onClick={()=>void submit('decide','not_eligible')}>{t.not_eligible}</Button></>}
      </div>}
    </Card>
    <Card><h2 className="bt-heading">{t.history}</h2>{history.isPending ? <State kind="loading" title={t.loading} body={t.lead}/> : history.error ? <State kind="error" title={t.error} body={t.errorBody}><Button onClick={()=>void history.refetch()}>{t.retry}</Button></State> : !history.data?.items.length ? <State title={t.empty} body={t.emptyBody}/> : <><p>{t.total}: {formatNumber(history.data.total,locale)}</p><ol>{history.data.items.map(item=><li key={item.operation_id}><p>{t[item.verdict]}</p><p>{item.reason??t.redacted}</p></li>)}</ol></>}
      <Button disabled={page===1||busy} onClick={()=>setPage(value=>value-1)}>{t.previous}</Button><Button disabled={!history.data||page*25>=history.data.total||busy} onClick={()=>setPage(value=>value+1)}>{t.next}</Button>
    </Card>
  </PageBody></PageFrame>;
}
