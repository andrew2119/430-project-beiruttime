'use client';
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card, Input, BidiReference } from '@beirut-time/ui';
import type { PrivateApplication } from '@contracts/contracts-identity/accounts';
import { authenticatedRequest, useSession } from './session';
import { ErrorNotice, SessionPrompt, syntheticFile, useIdentityCopy } from './shared';

const path = '/api/web/v1/identity/v1/private-seller/applications';
export default function SellerView() {
  const session = useSession();
  const { t } = useIdentityCopy();
  return <div className="identity-page"><header className="identity-heading"><p className="eyebrow">{t.privateSelling}</p><h1>{t.sellerTitle}</h1><p>{t.sellerSubtitle}</p></header>
    {!session ? <Card><SessionPrompt next="/seller/verification"/></Card> : <SellerForm key={session.access_fingerprint} fingerprint={session.access_fingerprint}/>}
  </div>;
}
function SellerForm({ fingerprint }: { fingerprint: string }) {
  const { t, locale } = useIdentityCopy();
  const client = useQueryClient();
  const queryKey = ['private-seller',fingerprint];
  const query = useQuery({ queryKey, queryFn: ({ signal }) => authenticatedRequest<{application:PrivateApplication|null}>(`${path}/me`,{signal,accessFingerprint:fingerprint}), retry:false });
  const [pending,setPending] = useState(false);
  const [error,setError] = useState<unknown>(null);
  const operation = useRef<{body:string;key:string}|null>(null);
  const status = useRef<HTMLParagraphElement>(null);
  const application = query.data?.application;
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if(pending) return;
    const form=event.currentTarget;
    setPending(true);setError(null);
    try {
      const data = new FormData(form);
      const body = JSON.stringify({identity_name:data.get('identity_name'),contact:data.get('contact'),payout_reference:data.get('payout_reference'),
        identity_evidence:await syntheticFile(data.get('identity_evidence')),possession_evidence:await syntheticFile(data.get('possession_evidence')),expected_revision:application?.revision??0});
      if(operation.current?.body!==body) operation.current={body,key:crypto.randomUUID()};
      const result=await authenticatedRequest<{application:PrivateApplication}>(path,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':operation.current.key},body});
      client.setQueryData(queryKey,result);operation.current=null;form.reset();
      await client.invalidateQueries({queryKey});
      requestAnimationFrame(()=>status.current?.focus());
    } catch(failure) {setError(failure);} finally {setPending(false);}
  }
  const editable=!application||['correction','rejected'].includes(application.status);
  return <div className="identity-grid"><div className="identity-stack"><Card>
    {query.isPending?<p role="status">{t.loading}</p>:query.error?<><ErrorNotice error={query.error}/><Button onClick={()=>void query.refetch()}>{t.retry}</Button></>:<>
      {application?<div className="identity-stack"><p ref={status} tabIndex={-1} className="identity-status" data-state={application.status} role="status">{t[application.status]}</p><p>{t.caseReference}: <BidiReference>{application.id}</BidiReference></p><p>{t.revision} <BidiReference>{application.revision.toLocaleString(locale)}</BidiReference></p>{application.reason&&<p>{t.reason}: {application.reason}</p>}<p className="identity-muted">{t.saved}</p></div>:<p>{t.noApplication}</p>}
      {editable&&<form method="post" onSubmit={submit} className="identity-form" aria-busy={pending}>
        <label>{t.identityName}<Input name="identity_name" required minLength={2} maxLength={100} defaultValue={application?.identity_name}/></label>
        <label>{t.contact}<Input name="contact" required minLength={5} maxLength={254} defaultValue={application?.contact}/></label>
        <label>{t.payout}<Input name="payout_reference" required dir="ltr" pattern={'DEMO-[A-Za-z0-9\\-]{4,64}'} placeholder="DEMO-RECIPIENT" defaultValue={application?.payout_reference}/></label>
        <label>{t.identityProof}<Input type="file" name="identity_evidence" accept=".txt,text/plain" required aria-describedby="proof-hint"/></label>
        <label>{t.possessionProof}<Input type="file" name="possession_evidence" accept=".txt,text/plain" required aria-describedby="proof-hint"/></label>
        <p id="proof-hint" className="identity-muted">{t.proofHint}</p><Button disabled={pending}>{pending?t.working:t.sendApplication}</Button>
      </form>}
    </>}<ErrorNotice error={error}/>
  </Card></div><aside className="identity-stack"><div className="identity-demo">{t.demo}</div><Card><h2>{t.privacy}</h2><p>{t.noEvidencePublic}</p></Card></aside></div>;
}
