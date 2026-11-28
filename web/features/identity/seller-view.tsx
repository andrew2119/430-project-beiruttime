'use client';
import { useRef, useState } from 'react';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { ApiError } from '@/lib/api/client';
import { sellerApplicationRead } from './reads';
import { Button, Card, Input, State, StatusBadge, formatNumber } from '@beirut-time/ui/foundation';
import { PageHeader, PageFrame, PageBody } from '@/shell/foundation/page';
import { PossessionForm } from './possession-view';
import './rebuilt.css';
import type { PrivateApplication } from '@contracts/contracts-identity/accounts';
import { authenticatedRequest, useSession } from './session';
import { ErrorNotice, SessionPrompt, syntheticFile, useIdentityCopy } from './shared';

const path = '/api/web/v1/identity/v1/private-seller/applications';
export default function SellerView() {
  const session = useSession();
  const { t } = useIdentityCopy();
  return <PageFrame><PageHeader lead={t.privateSelling} title={t.sellerTitle} count={t.sellerSubtitle}/>
    <PageBody>{!session ? <Card><SessionPrompt next="/seller/verification"/></Card> : <SellerForm key={session.access_fingerprint} fingerprint={session.access_fingerprint}/>}
  </PageBody></PageFrame>;
}
function SellerForm({ fingerprint }: { fingerprint: string }) {
  const { t, locale } = useIdentityCopy();
  const query = usePageRead(sellerApplicationRead(fingerprint));
  const [acknowledged,setAcknowledged] = useState<PrivateApplication|null>(null);
  const [accessError,setAccessError] = useState<unknown>(null);
  const readError = accessError ?? query.error;
  const denied = readError instanceof ApiError && [401,403].includes(readError.status);
  const retained = acknowledged && acknowledged.revision > (query.data?.application?.revision ?? 0)
    ? {application:acknowledged} : query.data;
  const answer = denied ? undefined : retained;
  async function refetch() {
    const result = await query.refetch();
    if (!result.error) setAccessError(null);
  }
  const [pending,setPending] = useState(false);
  const [error,setError] = useState<unknown>(null);
  const operation = useRef<{body:string;key:string}|null>(null);
  const status = useRef<HTMLParagraphElement>(null);
  const application = answer?.application;
  async function submit(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if(pending) return;
    const form=event.currentTarget;
    setPending(true);setError(null);
    try {
      const data = new FormData(form);
      const body = operation.current?.body ?? JSON.stringify({identity_name:data.get('identity_name'),contact:data.get('contact'),payout_reference:data.get('payout_reference'),
        identity_evidence:await syntheticFile(data.get('identity_evidence')),possession_evidence:await syntheticFile(data.get('possession_evidence')),expected_revision:application?.revision??0});
      if(!operation.current) operation.current={body,key:crypto.randomUUID()};
      const result = await authenticatedRequest<{application:PrivateApplication}>(path,{method:'POST',accessFingerprint:fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':operation.current.key},body});
      setAcknowledged(result.application);
      operation.current=null;form.reset();
      await refetch();
      requestAnimationFrame(()=>status.current?.focus());
    } catch(failure) {
      if(failure instanceof ApiError && failure.status>=400 && failure.status<500 && ![408,429].includes(failure.status)) operation.current=null;
      if(failure instanceof ApiError && [401,403].includes(failure.status)) {
        form.reset();operation.current=null;setAccessError(failure);
      }
      setError(failure);
    } finally {setPending(false);}
  }
  const editable=!application||['correction','rejected'].includes(application.status);
  return <div className="account-grid"><div className="account-stack"><Card>
    {!answer && !readError?<State kind="loading" title={t.loading} body={t.working}/>:!answer && readError?<><ErrorNotice error={readError}/><Button onClick={()=>void refetch()}>{t.retry}</Button></>:<AnswerArrival view="seller-application">
      {application?<div className="account-stack"><p ref={status} tabIndex={-1} className="identity-status" data-state={application.status} role="status"><StatusBadge tone={application.status==='approved'?'success':application.status==='rejected'?'error':'neutral'}>{t[application.status]}</StatusBadge></p><p>{t.caseReference}: <bdi>{application.id}</bdi></p><p>{t.revision} <bdi>{formatNumber(application.revision,locale)}</bdi></p>{application.reason&&<p>{t.reason}: {application.reason}</p>}<p className="identity-muted">{t.saved}</p></div>:<p>{t.noApplication}</p>}
      {editable&&<SellerApplicationForm application={application} pending={pending} onSubmit={submit}/>}

    </AnswerArrival>}{answer && !!readError && <><ErrorNotice error={readError}/><Button onClick={()=>void refetch()}>{t.retry}</Button></>}<ErrorNotice error={error}/>{application?.status==='approved'&&<PossessionForm fingerprint={fingerprint}/>}
  </Card></div><aside className="account-stack"><div className="identity-demo">{t.demo}</div><Card><h2>{t.privacy}</h2><p>{t.noEvidencePublic}</p></Card></aside></div>;
}

export function SellerApplicationForm({application,pending,onSubmit}: {application?:PrivateApplication|null;pending:boolean;onSubmit:(event:React.FormEvent<HTMLFormElement>)=>void}) {
  const {t} = useIdentityCopy();
  return <form method="post" onSubmit={onSubmit} className="account-form" aria-busy={pending}>
        <Input label={t.identityName} name="identity_name" required defaultValue={application?.identity_name}/>
        <Input label={t.contact} name="contact" required defaultValue={application?.contact}/>
        <Input label={t.payout} name="payout_reference" required placeholder="DEMO-RECIPIENT" defaultValue={application?.payout_reference}/>
        <label className="account-file">{t.identityProof}<input type="file" name="identity_evidence" accept=".txt,text/plain" required aria-describedby="proof-hint"/></label>
        <label className="account-file">{t.possessionProof}<input type="file" name="possession_evidence" accept=".txt,text/plain" required aria-describedby="proof-hint"/></label>
        <p id="proof-hint" className="identity-muted">{t.proofHint}</p><Button type="submit" disabled={pending}>{pending?t.working:t.sendApplication}</Button>
      </form>;
}
