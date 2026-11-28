'use client';
import { useRef, useState } from 'react';
import { Button, Card, Checkbox, Input, State, formatNumber } from '@beirut-time/ui/foundation';
import type { ListingPossession } from '@contracts/contracts-identity/accounts';
import { authenticatedRequest } from './session';
import { ApiError } from '@/lib/api/client';
import { ErrorNotice, useIdentityCopy } from './shared';

export function PossessionForm({ fingerprint }: { fingerprint:string }) {
  const {t,locale} = useIdentityCopy();
  const [listing,setListing] = useState('');
  const [proof,setProof] = useState<ListingPossession|null>(null);
  const [loaded,setLoaded] = useState(false);
  const [pending,setPending] = useState(false);
  const [safe,setSafe] = useState(false);
  const [synthetic,setSynthetic] = useState(false);
  const [retryKind,setRetryKind] = useState<string|null>(null);
  const [error,setError] = useState<unknown>(null);
  const operation = useRef<{body:string;key:string;kind:string}|null>(null);
  const file = useRef<HTMLInputElement>(null);
  const base = `/api/web/v1/identity/v1/private-seller/listings/${encodeURIComponent(listing)}/possession`;
  async function run(kind:'read'|'issue'|'submit') {
    if(pending) return;
    setPending(true);setError(null);
    try {
      let body = '';
      if(operation.current && kind!=='read') {
        if(operation.current.kind!==kind) return;
        body=operation.current.body;
      } else if(kind==='submit') {
        const photo = file.current?.files?.[0];
        if(!photo || photo.size>1048576 || !safe || !synthetic) throw new Error();
        const bytes = new Uint8Array(await photo.arrayBuffer());
        let binary = ''; for(const byte of bytes) binary += String.fromCharCode(byte);
        body = JSON.stringify({expected_revision:proof?.revision??0,challenge_id:proof?.challenge_id,code:proof?.code,photo_base64:btoa(binary),safe_photo:safe,synthetic_photo:synthetic});
      } else if(kind==='issue') body = JSON.stringify({expected_revision:proof?.revision??0});
      if(kind!=='read' && !operation.current) { operation.current={body,key:crypto.randomUUID(),kind}; setRetryKind(kind); }
      const result = await authenticatedRequest<{proof:ListingPossession|null}>(kind==='read'?base:`${base}/${kind==='issue'?'challenges':'submissions'}`,{
        accessFingerprint:fingerprint,method:kind==='read'?'GET':'POST',
        ...(kind==='read'?{}:{headers:{'Content-Type':'application/json','Idempotency-Key':operation.current!.key},body})
      });
      setProof(result.proof);setLoaded(true);
      if(kind!=='read') {operation.current=null;setRetryKind(null);}
      if(kind==='submit' && file.current) file.current.value='';
    } catch(failure) {
      if(kind!=='read' && failure instanceof ApiError && failure.status>=400 && failure.status<500 && ![408,429].includes(failure.status)) {operation.current=null;setRetryKind(null);}
      if(failure instanceof ApiError && [401,403].includes(failure.status)) {
        operation.current=null;setRetryKind(null);
        setProof(null);setLoaded(false);setSafe(false);setSynthetic(false);if(file.current)file.current.value='';
      }
      setError(failure);
    } finally {setPending(false);}
  }
  return <Card><h2>{t.listingProof}</h2><p>{t.listingProofBody}</p>
    <Input label={t.listingReference} value={listing} disabled={pending || !!retryKind} onValueChange={value=>{setListing(value);setProof(null);setLoaded(false);if(file.current)file.current.value='';}}/>
    <Button disabled={pending || !listing} onClick={()=>void run('read')}>{t.readProof}</Button>
    {loaded && (proof?<div role="status"><p>{t[`proof_${proof.state}`]}</p><p>{proof.review?.reason}</p><p>{t.revision}: {formatNumber(proof.revision,locale)}</p>{proof.state==='issued'&&<><p>{t.proofCode}: <bdi>{proof.code}</bdi></p><p>{t.proofDeadline}: <bdi>{proof.expires_at}</bdi></p></>}</div>:<State title={t.noListingProof} body={t.issueHint}/>)}
    {loaded && (!proof || ['issued','expired','stale','correction','rejected'].includes(proof.state))&&<Button disabled={pending || !!retryKind && retryKind!=='issue'} onClick={()=>void run('issue')}>{t.issueProof}</Button>}
    {proof?.state==='issued'&&<form method="post" className="account-form" onSubmit={event=>{event.preventDefault();void run('submit');}}>
      <label className="account-file">{t.privatePhoto}<input ref={file} type="file" accept="image/png,.png" required disabled={pending || !!retryKind}/></label>
      <Checkbox label={t.safePhoto} checked={safe} onCheckedChange={setSafe} required disabled={pending || !!retryKind}/>
      <Checkbox label={t.syntheticPhoto} checked={synthetic} onCheckedChange={setSynthetic} required disabled={pending || !!retryKind}/>
      <Button type="submit" disabled={pending}>{pending?t.working:t.submitProof}</Button>
    </form>}
    {retryKind&&<Button disabled={pending} onClick={()=>void run(retryKind as 'issue'|'submit')}>{t.retry}</Button>}
    {pending&&<p role="status">{t.working}</p>}<ErrorNotice error={error}/>
  </Card>;
}
