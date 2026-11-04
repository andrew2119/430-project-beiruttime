'use client';
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BidiReference, Button, Card, Input } from '@beirut-time/ui';
import { normalizeDigits } from '@beirut-time/i18n';
import type { ConsentResult, PrivateConsent } from '@contracts/contracts-eligibility/consent';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest, useSession } from '../identity/session';
import { ErrorNotice, SessionPrompt, syntheticFile } from '../identity/shared';
import en from './en.json';
import ar from './ar.json';
const path='/api/web/v1/eligibility/v1/consents';
type Binding={request?:string;brand?:string;revision?:string};
function useCopy() {const locale=useLocale();return {locale,t:locale==='ar'?ar:en};}
export default function ConsentView({binding={}}:{binding?:Binding}) {
  const session=useSession();const {t}=useCopy();
  return <div className="identity-page"><header className="identity-heading"><p className="eyebrow">{t.eyebrow}</p><h1>{t.title}</h1><p>{t.intro}</p></header>
    {!session?<Card><SessionPrompt next="/consent"/></Card>:<ConsentForm key={session.access_fingerprint} fingerprint={session.access_fingerprint} binding={binding}/>}
  </div>;
}
function ConsentForm({fingerprint,binding}:{fingerprint:string;binding:Binding}) {
  const {locale,t}=useCopy();const client=useQueryClient();
  const queryKey=['consents',fingerprint];
  const query=useQuery({queryKey,queryFn:({signal})=>authenticatedRequest<{consents:PrivateConsent[]}>(path,{signal,accessFingerprint:fingerprint}),retry:false});
  const [decision,setDecision]=useState<'agree'|'refuse'|''>('');
  const [pending,setPending]=useState(false);const [error,setError]=useState<unknown>(null);
  const operation=useRef<{body:string;key:string}|null>(null);
  const withdrawals=useRef(new Map<string,string>());
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();if(pending||!decision)return;const form=event.currentTarget;
    setPending(true);setError(null);
    try {
      const data=new FormData(form);
      const revision=Number(normalizeDigits(String(data.get('request_revision'))));
      const body=JSON.stringify({request_id:data.get('request_id'),brand_id:data.get('brand_id'),request_revision:revision,purpose:'brand-request-identity',policy_version:'demo-identity-v1',decision,
        evidence:decision==='agree'?await syntheticFile(data.get('evidence')):null});
      if(operation.current?.body!==body)operation.current={body,key:crypto.randomUUID()};
      await authenticatedRequest<ConsentResult>(path,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':operation.current.key},body});
      operation.current=null;form.reset();setDecision('');await client.invalidateQueries({queryKey});
    }catch(failure){setError(failure);}finally{setPending(false);}
  }
  async function withdraw(record:PrivateConsent) {
    if(pending)return;setPending(true);setError(null);
    const scope=`${record.id}:${record.revision}`;
    if(!withdrawals.current.has(scope))withdrawals.current.set(scope,crypto.randomUUID());
    try{
      await authenticatedRequest<ConsentResult>(`${path}/${record.id}/withdraw`,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':withdrawals.current.get(scope)!},body:JSON.stringify({expected_revision:record.revision})});
      withdrawals.current.delete(scope);await client.invalidateQueries({queryKey});
      requestAnimationFrame(()=>document.getElementById(`consent-${record.id}`)?.focus());
    }catch(failure){setError(failure);}finally{setPending(false);}
  }
  const code=error instanceof ApiError?error.code:'';
  const consentError=(t as Record<string,string>)[code];
  return <div className="identity-grid"><div className="identity-stack"><Card><h2>{t.record}</h2><form method="post" className="identity-form" onSubmit={submit} aria-busy={pending}>
    <label>{t.request}<Input name="request_id" required dir="ltr" pattern={'[a-fA-F0-9\\-]{36}'} defaultValue={binding.request}/></label>
    <label>{t.brand}<Input name="brand_id" required dir="ltr" pattern={'[a-fA-F0-9\\-]{36}'} defaultValue={binding.brand}/></label>
    <label>{t.revision}<Input name="request_revision" required inputMode="numeric" pattern="[0-9٠-٩۰-۹]{1,9}" maxLength={9} defaultValue={binding.revision??'1'}/></label>
    <p>{t.purpose}</p><p className="identity-muted">{t.policy} <BidiReference>demo-identity-v1</BidiReference></p>
    <fieldset className="consent-choices"><legend className="sr-only">{t.record}</legend><label><input type="radio" name="decision" value="agree" checked={decision==='agree'} onChange={()=>setDecision('agree')} required/>{t.agree}</label><label><input type="radio" name="decision" value="refuse" checked={decision==='refuse'} onChange={()=>setDecision('refuse')} required/>{t.refuse}</label></fieldset>
    {decision==='agree'&&<label>{t.evidence}<Input name="evidence" type="file" accept=".txt,text/plain" required aria-describedby="consent-proof"/><small id="consent-proof">{t.proofHint}</small></label>}
    <Button disabled={pending||!decision}>{pending?t.working:t.record}</Button>
  </form>{consentError?<p className="identity-feedback" role="alert">{consentError}</p>:<ErrorNotice error={error}/>}</Card>
  <Card><h2>{t.saved}</h2>{query.isPending?<p role="status">{t.loading}</p>:query.error?<><ErrorNotice error={query.error}/><Button onClick={()=>void query.refetch()}>{t.retry}</Button></>:!query.data?.consents.length?<p>{t.empty}</p>:<ul className="consent-records">{query.data.consents.map(record=><li key={record.id}><p id={`consent-${record.id}`} tabIndex={-1} className="identity-status">{t[record.status]}</p><p>{t.reference}: <BidiReference>{record.id}</BidiReference></p><p>{t.request}: <BidiReference>{record.request_id}</BidiReference></p><p>{t.brand}: <BidiReference>{record.brand_id}</BidiReference></p><p><BidiReference>{record.policy_version}</BidiReference></p><p>{t.revision}: {record.request_revision.toLocaleString(locale)}</p>{record.status==='active'&&<Button className="button-secondary" disabled={pending} onClick={()=>void withdraw(record)}>{t.withdraw}</Button>}</li>)}</ul>}</Card>
  </div><aside className="identity-stack"><Card><p>{t.privacy}</p><p>{t.scope}</p></Card><div className="identity-demo">{t.withdrawInfo}</div></aside></div>;
}
