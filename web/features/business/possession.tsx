'use client';
import { useId, useState } from 'react';
import { useBusinessRead } from './reads';
import { Button, Card, Checkbox, Input, Label, State, formatNumber } from '@beirut-time/ui/foundation';
import type { ListingProof, Page, ProofHistory } from '@contracts/contracts-identity/businesses/workspace_v2';
import { useAccessContext } from '@/shell/access-context';
import { useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { useLocale } from '@/shell/locale-context';
import { businessFile, businessRequest } from './transport';
import { BusinessLoading, Feedback, Select, integer, text, useAction, useCopy } from './components';
import { accessDenied, PendingRecovery, CommandForm, useCommandSnapshot, usePendingCommands, type PendingChange } from './command-form';

export function ProofControls({ proof, refresh, onPending, onDenied }: { proof: ListingProof; refresh: () => void; onPending?: PendingChange; onDenied?: (error: unknown) => void }) {
  const t = useCopy(), session = useSession(), fileId = useId(), action = useAction();
  const [safe, setSafe] = useState(false);
  const {busy, onPending: setBusy} = usePendingCommands(!onPending);
  const pending: PendingChange = (value, operationId, operation) => {setBusy(value, operationId, operation);onPending?.(value, operationId, operation);};
  const envelope = { actor_id: session?.principal.actor.subject_id, subject_id: proof.subject_id, watch_id: proof.watch_id,
    watch_revision: proof.watch_revision, listing_revision: proof.listing_revision, expected_revision: proof.revision };
  return <Card>
    <p>{proof.state ? t[proof.state] : t.unverified} · {t.revision} {proof.revision}</p>
    <p>{t.watchRevision}: {proof.watch_revision} · {t.listingRevision}: {proof.listing_revision}</p>
    {proof.expires_at && <p>{t.codeExpiry}: <time dateTime={proof.expires_at}>{proof.expires_at}</time></p>}
    {proof.can_issue && <CommandForm disabled={busy} onPending={pending} onComplete={refresh} submit={(_, operation) => operation.send('/v2/listing-possession/challenges',{...envelope,kind:'issue'})}>
      <p>{t.issueProof}</p>
    </CommandForm>}
    {proof.can_submit && <CommandForm disabled={busy} onPending={pending} onComplete={refresh} submit={async (data, operation) => {
      const file = data.get('photo');
      if (!(file instanceof File) || !file.size || !safe || !proof.challenge_id) throw new ApiError(422,'private_evidence_required','');
      const evidence = await operation.photo(file, {watch_id:proof.watch_id, listing_revision:String(proof.listing_revision), challenge_id:proof.challenge_id});
      return operation.send('/v2/listing-possession/submissions', {...envelope,kind:'submit',challenge_id:proof.challenge_id,code:text(data,'code'),evidence_ref:evidence});
    }}>
      <Input name="code" label={t.code} inputMode="numeric" required />
      <Label htmlFor={fileId}>{t.privatePhoto}</Label><input id={fileId} name="photo" type="file" accept="image/jpeg,image/png,image/webp" required />
      <Checkbox label={t.safePhoto} checked={safe} onCheckedChange={setSafe} required />
    </CommandForm>}
    {proof.can_assign && <CommandForm disabled={busy} onPending={pending} onComplete={refresh} submit={(data, operation) => operation.send('/v2/listing-possession/assignments', {
      ...envelope,kind:'assign',reviewer_id:text(data,'reviewer'),reason:text(data,'reason'),
    })}><Input name="reviewer" label={t.reviewer} required /><Input name="reason" label={t.reason} required /></CommandForm>}
    {proof.can_decide && <>
      {proof.evidence_available ? <Button disabled={action.pending} onClick={() => void action.run(async () => {
        try {
        const blob = await businessFile(`/v2/listing-possession/evidence/${proof.watch_id}`,session?.access_token ?? null);
        const url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href=url; link.download='private-watch-photo'; link.click(); URL.revokeObjectURL(url);
        } catch (error) { if (accessDenied(error)) onDenied?.(error); throw error; }
      },false)}>{t.openEvidence}</Button> : <State title={t.evidenceIncomplete} body={t.noAuthority} />}
      <CommandForm disabled={busy} onPending={pending} onComplete={refresh} submit={(data, operation) => operation.send('/v2/listing-possession/decisions', {
        ...envelope,kind:'decide',assignment_revision:proof.assignment_revision,verdict:text(data,'verdict'),reason:text(data,'reason'),
      })}><Select name="verdict" label={t.decision} options={(['approved','correction','rejected','suspended'] as const).map(value => ({value,label:t[value]}))} />
        <Input name="reason" label={t.reason} required /></CommandForm>
    </>}
    {!proof.can_issue && !proof.can_submit && !proof.can_assign && !proof.can_decide && <State title={t.pending} body={t.noAuthority} />}
    <Feedback error={action.error} />
  </Card>;
}
export function ListingPossession() {
  const t = useCopy(), locale = useLocale(), access = useAccessContext();
  const [selection,setSelection] = useState<{watch:string;revision:number}|null>(null), [page,setPage] = useState(1);
  const {busy, onPending: setBusy, recovery} = usePendingCommands();
  const [denial, setDenial] = useState<unknown>(null);
  const proof = useBusinessRead({queryKey:['business-v2','possession',access.fingerprint,selection],
    queryFn:() => businessRequest<ListingProof>(`/v2/listing-possession/listings/${encodeURIComponent(selection!.watch)}?listing_revision=${selection!.revision}`),enabled:!!selection,retry:false});
  const history = useBusinessRead({queryKey:['business-v2','possession-history',access.fingerprint,selection,page],
    queryFn:() => businessRequest<Page<ProofHistory>>(`/v2/listing-possession/history/${encodeURIComponent(selection!.watch)}?page=${page}&page_size=25`),enabled:!!selection,retry:false});
  if (!denial && accessDenied(history.error)) setDenial(history.error);
  const denied = !!denial || accessDenied(proof.error) || accessDenied(history.error);
  const commandProof = useCommandSnapshot(proof.isError || denied ? undefined : proof.data, busy, access.fingerprint, denied);
  return <Card><h2>{t.listingProof}</h2><p>{t.listingHelp}</p>
    <form className="business-form" onSubmit={event => {event.preventDefault();if (busy) return;const data=new FormData(event.currentTarget);setPage(1);setSelection({watch:text(data,'watch'),revision:integer(data,'listing_revision')});}}>
      <Input name="watch" label={t.watchId} required /><Input name="listing_revision" label={t.listingRevision} inputMode="numeric" required />
      <Button type="submit" disabled={busy}>{t.open}</Button>
    </form>
    {selection && <Button disabled={busy} onClick={() => {void Promise.all([proof.refetch(),history.refetch()]).then(([record, rows]) => { if (!record.isError && !rows.isError) setDenial(null); });}}>{t.reload}</Button>}
    {selection && proof.isPending && <BusinessLoading />}
    <Feedback error={denial ?? proof.error} />
    {busy && !commandProof ? <PendingRecovery recovery={recovery} onPending={setBusy} refresh={() => void proof.refetch()} /> : null}
    {commandProof && <ProofControls key={`${access.fingerprint}:${commandProof.watch_id}:${commandProof.revision}`} proof={commandProof} onDenied={setDenial} onPending={setBusy} refresh={() => {void proof.refetch();void history.refetch();}} />}
    {selection && <><h3>{t.proofHistory}</h3><Feedback error={history.error} />{history.isPending && <BusinessLoading />}</>}
    {commandProof && !proof.isError && history.data && !history.isError && <><p>{t.serverTotal}: {formatNumber(history.data.total,locale)}</p>
      {!history.data.items.length && <State title={t.noReviews} body="" />}
      <ol>{history.data.items.map(item => <li key={item.revision}><p>{t[item.state]} · {t.revision} {item.revision}</p><p>{item.reason}</p><time dateTime={item.recorded_at}>{item.recorded_at}</time></li>)}</ol>
      <Button disabled={busy || page<=1} onClick={() => setPage(value=>value-1)}>{t.previous}</Button>
      <Button disabled={busy || page*history.data.page_size>=history.data.total} onClick={() => setPage(value=>value+1)}>{t.next}</Button>
    </>}
  </Card>;
}
