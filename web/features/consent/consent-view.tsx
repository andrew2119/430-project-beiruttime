'use client';
import { useRef, useState } from 'react';
import { Button, ButtonLink, Card, Input, Label, Radio, RowSkeleton, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame as PageLayout, PageHeader } from '@/shell/foundation/page';
import { normalizeDigits } from '@beirut-time/i18n';
import type { ConsentResult, PrivateConsent } from '@contracts/contracts-eligibility/consent';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest, signInHref, useSession } from '../identity/session';
import { useConsentRead } from './use-consent-read';
import { DecisionView } from '../eligibility/decision-view';
import en from './en.json';
import ar from './ar.json';
import './styles.css';
const path='/api/web/v1/eligibility/v1/consents';
type Binding={request?:string;brand?:string;revision?:string};
function useCopy() {const locale=useLocale();return {locale,t:locale==='ar'?ar:en};}
export default function ConsentView({binding={}}:{binding?:Binding}) {
  const session=useSession();const {locale,t}=useCopy();
  return <PageLayout><PageHeader lead={t.eyebrow} title={t.title} count={t.intro}/><PageBody>
    {!session?<State title={t.signInRequired} body={t.privacy}><ButtonLink href={signInHref('/consent',locale)}>{t.signin}</ButtonLink></State>:<ConsentForm key={session.access_fingerprint} fingerprint={session.access_fingerprint} binding={binding}/>}
  {session?.principal.permissions.includes('eligibility.identity.review')&&<DecisionView key={session.access_fingerprint} fingerprint={session.access_fingerprint}/>}
  </PageBody></PageLayout>;
}
function ConsentForm({fingerprint,binding}:{fingerprint:string;binding:Binding}) {
  const {locale,t}=useCopy();const [page,setPage]=useState(0);
  const query=useConsentRead(fingerprint,page);
  const [decision,setDecision]=useState<'agree'|'refuse'|''>('');
  const [pending,setPending]=useState(false);const [error,setError]=useState<unknown>(null);
  const [uncertain,setUncertain]=useState(false);
  const [acknowledged,setAcknowledged]=useState<{operation:string;consent:string}|null>(null);
  const [blocked,setBlocked]=useState<Set<string>>(new Set());
  const [reference,setReference]=useState<string|null>(null);
  const operation=useRef<{body:string;key:string}|null>(null);
  const [withdrawalReferences,setWithdrawalReferences]=useState<Record<string,string>>({});
  const withdrawals=useRef(new Map<string,string>());
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();if(pending||!decision)return;const form=event.currentTarget;
    setPending(true);setError(null);
    try {
      if(!operation.current){
        const data=new FormData(form);let evidence:string|null=null;
        if(decision==='agree'){
          const file=data.get('evidence');
          if(!(file instanceof File)||file.size<5||file.size>65536||!file.name.toLowerCase().endsWith('.txt'))throw new ApiError(422,'evidence_required','');
          evidence=await file.text();if(!evidence.startsWith('DEMO:'))throw new ApiError(422,'evidence_required','');
        }
        operation.current={key:crypto.randomUUID(),body:JSON.stringify({request_id:data.get('request_id'),brand_id:data.get('brand_id'),request_revision:Number(normalizeDigits(String(data.get('request_revision')))),purpose:'brand-request-identity',policy_version:'demo-identity-v1',decision,evidence})};
      }
      setReference(operation.current.key);
      const answer=await authenticatedRequest<ConsentResult>(path,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':operation.current.key},body:operation.current.body});
      setAcknowledged({operation:operation.current.key,consent:answer.consent.id});
      operation.current=null;setReference(null);setUncertain(false);form.reset();setDecision('');await query.refetch();
    }catch(failure){
      setError(failure);
      if(failure instanceof ApiError&&[400,404,409,422].includes(failure.status)){operation.current=null;setReference(null);setUncertain(false);}else setUncertain(true);
    }finally{setPending(false);}
  }
  async function withdraw(record:PrivateConsent) {
    if(pending)return;setPending(true);setError(null);
    setBlocked(previous=>new Set(previous).add(record.id));
    const scope=`${record.id}:${record.revision}`;
    if(!withdrawals.current.has(scope))withdrawals.current.set(scope,crypto.randomUUID());
    const withdrawalReference=withdrawals.current.get(scope)!;
    setWithdrawalReferences(previous=>({...previous,[record.id]:withdrawalReference}));
    try{
      await authenticatedRequest<ConsentResult>(`${path}/${record.id}/withdraw`,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':withdrawals.current.get(scope)!},body:JSON.stringify({expected_revision:record.revision})});
      query.refetch();
    }catch(failure){setError(failure);}finally{setPending(false);}
  }
  const code=error instanceof ApiError?error.code:'';
  const message=(t as Record<string,string>)[code]??(error instanceof ApiError&&error.status===403?t.denied:t.pendingRecovery);
  return <div className="consent-stack"><Card><h2 className="bt-heading">{t.record}</h2><form method="post" className="consent-stack" onSubmit={submit} aria-busy={pending}>
    <fieldset disabled={pending||uncertain} className="consent-fields">
      <Input label={t.request} name="request_id" required defaultValue={binding.request}/>
      <Input label={t.brand} name="brand_id" required defaultValue={binding.brand}/>
      <Input label={t.revision} name="request_revision" required inputMode="numeric" defaultValue={binding.revision??'1'}/>
      <p className="bt-text">{t.purpose}</p><p className="bt-caption">{t.policy} <bdi dir="ltr">demo-identity-v1</bdi></p>
      <Radio label={t.agree} name="decision" value="agree" checked={decision==='agree'} onCheckedChange={()=>setDecision('agree')} required/>
      <Radio label={t.refuse} name="decision" value="refuse" checked={decision==='refuse'} onCheckedChange={()=>setDecision('refuse')} required/>
      {decision==='agree'&&<div className="bt-field"><Label htmlFor="consent-evidence">{t.evidence}</Label><input id="consent-evidence" className="bt-input" name="evidence" type="file" accept=".txt,text/plain" required aria-describedby="consent-proof"/><p id="consent-proof" className="bt-field-hint">{t.proofHint}</p></div>}
    </fieldset>
    {reference&&<p className="bt-caption">{t.actionReference}: <bdi dir="ltr">{reference}</bdi></p>}
    <Button type="submit" busy={pending} disabled={pending||!decision}>{uncertain?t.retry:t.record}</Button>
  </form>{acknowledged&&<p className="bt-caption" role="status">{t.recorded}: <bdi dir="ltr">{acknowledged.consent}</bdi> · {t.actionReference}: <bdi dir="ltr">{acknowledged.operation}</bdi></p>}{Boolean(error)&&<State kind="error" title={t.error} body={message}/>}</Card>
  <Card><h2 className="bt-heading">{t.saved}</h2>{query.data?<>
    <p className="bt-number">{t.total}: {formatNumber(query.data.total,locale)}</p>
    {Boolean(query.error)&&<State kind="error" title={t.error} body={query.denied?t.denied:t.unavailable}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State>}
    {!query.data.consents.length?<State title={t.empty} body={t.scope}/>:<ul className="consent-records">{query.data.consents.map(record=><li key={record.id} className="consent-record">
      <p className="bt-text" role="status">{blocked.has(record.id)&&record.status==='active'?t.withdrawalLocal:t[record.status]}</p>
      <p className="bt-caption">{t.reference}: <bdi dir="ltr">{record.id}</bdi></p>
      <p className="bt-caption">{t.request}: <bdi dir="ltr">{record.request_id}</bdi></p>
      <p className="bt-caption">{t.brand}: <bdi dir="ltr">{record.brand_id}</bdi></p>
      <p className="bt-caption">{t.revision}: {formatNumber(record.request_revision,locale)}</p>
      {withdrawalReferences[record.id]&&<p className="bt-caption">{t.actionReference}: <bdi dir="ltr">{withdrawalReferences[record.id]}</bdi></p>}
      {record.status==='active'&&<Button variant="outline" disabled={pending} onClick={()=>void withdraw(record)}>{blocked.has(record.id)?t.retryWithdrawal:t.withdraw}</Button>}
    </li>)}</ul>}
    <div className="consent-pagination"><Button variant="outline" disabled={page===0||query.isFetching} onClick={()=>setPage(value=>value-1)}>{t.previous}</Button><Button variant="outline" disabled={(page+1)*25>=query.data.total||query.isFetching} onClick={()=>setPage(value=>value+1)}>{t.next}</Button></div>
  </>:query.error?<State kind="error" title={t.error} body={query.denied?t.denied:t.unavailable}><Button onClick={()=>void query.refetch()}>{t.retry}</Button></State>:<div role="status" aria-label={t.loading}><RowSkeleton/></div>}</Card>
  <Card><p className="bt-text">{t.privacy}</p><p className="bt-text">{t.scope}</p><p className="bt-text">{t.withdrawInfo}</p></Card></div>;
}
