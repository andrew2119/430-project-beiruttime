'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, ButtonLink, Checkbox, Label, State, RowSkeleton, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import type { MessagePhotos, PhotoPage, PhotoScope } from '@contracts/contracts-comms/message-photos';
import { copy } from './copy';
import { readFailure, recoveredRead } from './recovery';
import { PhotoAction, withSignal } from './action';
import { PrivatePhoto } from './private-photo';
import './styles.css';

type Props = { accessFingerprint: string; scope: PhotoScope; provider?: MessagePhotos };
/** The caller changes accessFingerprint immediately on identity, membership or assignment change. */
export function MessagePhotoView(props: Props) {
  return <PhotoForm key={`${props.accessFingerprint}:${props.scope.actor}:${props.scope.business}:${props.scope.thread}:${props.scope.watch}:${props.scope.revision}`} accessFingerprint={props.accessFingerprint} scope={props.scope} provider={props.provider}/>;
}
function PhotoForm({ provider }: Props) {
  const locale = useLocale(), t = copy[locale];
  const [file, setFile] = useState<File | null>(null), [checked, setChecked] = useState(false);
  const [status, setStatus] = useState<'empty' | 'loading' | 'pending' | 'attached' | 'unavailable' | 'denied' | 'invalid'>('empty');
  const [page, setPage] = useState<PhotoPage | null>(null), [offset, setOffset] = useState(0);
  const [preview, setPreview] = useState<Blob | null>(null), [refresh, setRefresh] = useState(0);
  const [locked, setLocked] = useState(false);
  const [rejection, setRejection] = useState<'stale_revision' | 'photo_limit' | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const action = useRef<PhotoAction | null>(null), busy = useRef(false), controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const needsRecovery = useRef(false);
  const accessGeneration = useRef(0);
  function denyAccess() {
    accessGeneration.current += 1;
    needsRecovery.current = true;
    setRejection(null);
    controller.current?.abort();
    setLocked(true); setPage(null); setFile(null); setChecked(false); setPreview(null); setStatus('denied');
    if (input.current) input.current.value = '';
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort(); }; }, []);
  useEffect(() => {
    if (!provider) return;
    const generation = accessGeneration.current;
    const request = new AbortController();
    const timer = window.setTimeout(() => { request.abort(); if (generation === accessGeneration.current) { setPage(null); setPreview(null); setStatus('unavailable'); } }, 10000);
    provider.list(offset, request.signal).then(result => { if (!request.signal.aborted && generation === accessGeneration.current) { window.clearTimeout(timer); if (!needsRecovery.current) { setPage(result); setStatus(recoveredRead); } } }).catch((error: unknown) => {
      window.clearTimeout(timer);
      if (!request.signal.aborted && generation === accessGeneration.current) {
        const failure = readFailure(error);
        if (failure === 'denied') denyAccess();
        else { setPreview(null); setStatus(failure); }
      }
    });
    return () => { request.abort(); window.clearTimeout(timer); };
  }, [provider, offset, refresh]);
  // Private pixels are short-lived even if an access-change signal is delayed.
  useEffect(() => {
    if (!preview) return;
    const timer = window.setTimeout(() => setPreview(null), 15000);
    return () => window.clearTimeout(timer);
  }, [preview]);
  async function share() {
    if (!provider || !file || !checked || busy.current || rejection) return;
    busy.current = true; setStatus('pending');
    const generation = accessGeneration.current;
    const request = new AbortController(); controller.current = request;
    const timer = window.setTimeout(() => request.abort(), 10000);
    setLocked(true);
    action.current ??= new PhotoAction(() => crypto.randomUUID());
    const current = action.current;
    try {
      const result = await current.run(provider, file, request.signal);
      if (mounted.current && generation === accessGeneration.current && !request.signal.aborted && result.state === 'attached') {
        setStatus('attached'); setRefresh(value => value + 1);
      }
    } catch (error) {
      if (mounted.current && generation === accessGeneration.current) {
        const code = error && typeof error === 'object' && 'code' in error ? error.code : '';
        if (code === 'denied' || code === 'unauthorized') denyAccess();
        else if (code === 'unsafe_photo' || code === 'classified_route_required') { setStatus('invalid'); setLocked(false); action.current = null; }
        else if (code === 'stale_revision' || code === 'photo_limit') { setRejection(code); setStatus('empty'); }
        else setStatus('pending');
      }
    } finally { window.clearTimeout(timer); busy.current = false; }
  }
  async function recover() {
    if (!provider || busy.current || rejection === 'stale_revision') return;
    busy.current = true; setStatus('loading');
    const generation = accessGeneration.current;
    const request = new AbortController(); controller.current = request;
    const timer = window.setTimeout(() => request.abort(), 10000);
    try {
      const result = await withSignal(provider.list(offset, request.signal), request.signal);
      if (mounted.current && generation === accessGeneration.current && !request.signal.aborted) {
        action.current = null; needsRecovery.current = false; setRejection(null);
        setFile(null); setChecked(false); setPreview(null); setPage(result);
        if (input.current) input.current.value = '';
        setLocked(false); setStatus('empty');
      }
    } catch (error) {
      if (mounted.current && generation === accessGeneration.current) {
        const failure = readFailure(error);
        if (failure === 'denied') denyAccess();
        else setStatus(failure);
      }
    } finally { window.clearTimeout(timer); busy.current = false; }
  }
  async function show(photo: string) {
    if (!provider || busy.current) return;
    setPreview(null); setStatus('loading'); busy.current = true;
    const generation = accessGeneration.current;
    const request = new AbortController(); controller.current = request;
    const timer = window.setTimeout(() => request.abort(), 10000);
    try {
      const blob = await withSignal(provider.bytes(photo, request.signal), request.signal);
      if (mounted.current && generation === accessGeneration.current && !request.signal.aborted) { setPreview(blob); setStatus('empty'); }
    } catch (error) {
      if (mounted.current && generation === accessGeneration.current) {
        const failure = readFailure(error);
        if (failure === 'denied') denyAccess();
        else { setStatus(failure); setPreview(null); }
      }
    } finally { window.clearTimeout(timer); busy.current = false; }
  }
  const state = !provider ? 'unavailable' : rejection ?? status;
  return <PageFrame><PageHeader title={t.title} lead={t.lead}/><PageBody>
    <Label htmlFor="watch-photo">{t.choose}</Label>
    <input className="bt-input" ref={input} id="watch-photo" type="file" aria-label={t.choose} accept="image/jpeg,image/png,image/webp" disabled={locked} onChange={event => {
      const chosen = event.target.files?.[0] ?? null;
      if (chosen && (chosen.size > 5 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(chosen.type))) { setFile(null); setStatus('invalid'); return; }
      setFile(chosen); setStatus('empty');
    }}/>
    <Checkbox checked={checked} disabled={locked} onCheckedChange={setChecked} label={t.confirm}/>
    <Button disabled={!provider || !file || !checked || !!rejection || status === 'attached' || status === 'loading'} onClick={() => void share()}>{locked ? t.retry : t.send}</Button>
    {(state === 'loading' || (provider && !page && state === 'empty')) && <RowSkeleton/>}
    {state === 'empty' && page?.total === 0 && <State title={t.empty} body={t.emptyBody}/>}
    {state === 'pending' && <State kind="loading" title={t.pending} body={t.pendingBody}/>}
    {state === 'attached' && <State title={t.attached} body={t.attachedBody}><Button onClick={() => { action.current = null; setLocked(false); setFile(null); setChecked(false); setStatus('empty'); if (input.current) input.current.value = ''; }}>{t.choose}</Button></State>}
    {state === 'stale_revision' && <State kind="error" title={t.stale} body={t.staleBody}><ButtonLink href={`/${locale}/inbox`}>{t.review}</ButtonLink></State>}
    {state === 'photo_limit' && <State kind="error" title={t.limit} body={t.limitBody}><Button onClick={() => void recover()}>{t.recheck}</Button><ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink></State>}
    {state === 'invalid' && <State kind="error" title={t.choose} body={t.invalid}/>}
    {state === 'denied' && <State kind="error" title={t.denied} body={t.deniedBody}><Button onClick={() => void recover()}>{t.recheck}</Button><ButtonLink href={`/${locale}/inbox`}>{t.support}</ButtonLink></State>}
    {state === 'unavailable' && <State kind="error" title={t.unavailable} body={t.recovery}><Button onClick={() => needsRecovery.current ? void recover() : setRefresh(value => value + 1)}>{t.retry}</Button></State>}
    {page && <><p>{t.total}: {formatNumber(page.total, locale)}</p>{page.items.map(photo => <Button key={photo.id} onClick={() => void show(photo.id)}>{t.view}</Button>)}
      <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>{t.previous}</Button>
      <Button disabled={page.next_offset === null} onClick={() => setOffset(page.next_offset ?? 0)}>{t.next}</Button></>}
    {preview && <><PrivatePhoto bytes={preview} label={t.alt} unavailable={t.unavailable}/><Button onClick={() => setPreview(null)}>{t.close}</Button></>}
  </PageBody></PageFrame>;
}
