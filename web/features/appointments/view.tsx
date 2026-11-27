'use client';

import { useEffect, useRef, useState } from 'react';
import { Button, Card, Checkbox, Input, Select, State, formatNumber } from '@beirut-time/ui/foundation';
import type { Binding, Command, Purpose, Visit } from '@contracts/contracts-service/appointments';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { usePageRead } from '@/lib/page-speed/read';
import { ApiError } from '@/lib/api/client';
import { findOperation, sendVisit, visitRead } from './api';
import { VisitCommand } from './command';
import { visitTime } from './time';
import en from './en.json';
import ar from './ar.json';

export type AppointmentProps = {binding:Binding; businessStaff:boolean; appointmentId?:string};
export default function Appointments(props:AppointmentProps) {
  const access = useAccessContext();
  return <AppointmentForm key={[access.fingerprint,props.binding.actor_id,props.binding.subject_id,props.binding.watch_id,props.binding.organization_id,props.appointmentId].join(':')} binding={props.binding} businessStaff={props.businessStaff} appointmentId={props.appointmentId}/>;
}
function AppointmentForm({binding,businessStaff,appointmentId}:AppointmentProps) {
  const locale = useLocale(), t = locale === 'ar' ? ar : en;
  const access = useAccessContext(), fingerprint = access.fingerprint;
  const [appointment] = useState(()=>appointmentId ?? crypto.randomUUID());
  const [known,setKnown] = useState(Boolean(appointmentId));
  const read = usePageRead(known && fingerprint ? visitRead(fingerprint,appointment,binding.organization_id) : null);
  const [local,setLocal] = useState<Visit|null>(null);
  const [purpose,setPurpose] = useState<Purpose|null>(null);
  const [date,setDate] = useState(''), [time,setTime] = useState(''), [duration,setDuration] = useState('30');
  const [error,setError] = useState(''), [busy,setBusy] = useState(false);
  const [candidates,setCandidates] = useState<string[]>([]), [selected,setSelected] = useState('');
  const [ack,setAck] = useState(false);
  const [pending,setPending] = useState<Command|null>(null);
  const receipt = useRef(new VisitCommand()), controllers = useRef(new Set<AbortController>());
  const visit = local ?? read.data;
  useEffect(()=>{
    const commands = controllers.current, state = receipt.current;
    const clear = ()=>{commands.forEach(item=>item.abort());commands.clear();state.clear();setPending(null);setLocal(null);setDate('');setTime('');setError('denied');};
    window.addEventListener('bt:access-change',clear);
    return ()=>{window.removeEventListener('bt:access-change',clear);commands.forEach(item=>item.abort());state.clear();};
  },[]);
  const messages = {placeholder:t.choose,filter:t.filter,emptyTitle:t.none,emptyBody:t.noneBody,close:t.close,
    loading:t.loading,errorTitle:t.errorTitle,errorBody:t.unavailable,retry:t.reload};
  const errorText = error in t ? t[error as keyof typeof t] : t.error;
  const denied = !fingerprint || error === 'denied' || (read.error instanceof ApiError && [401,403].includes(read.error.status));
  const uncertain = Boolean(pending);
  async function perform(command:Command,lookup=false) {
    if (!fingerprint || busy) return;
    const controller = new AbortController();controllers.current.add(controller);
    setBusy(true);setError('');
    try {
      const result = await (lookup ? findOperation(command,fingerprint,controller.signal) : sendVisit(command,fingerprint,controller.signal));
      if (controller.signal.aborted) return;
      receipt.current.acknowledge(result);setPending(null);setKnown(true);setLocal(result);setCandidates([]);setSelected('');setAck(false);
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError) {
        const code = [401,403].includes(failure.status) ? 'denied' : failure.code;
        setError(code);
        if (failure.status < 500 && code !== 'duplicate_conflict' && !(lookup && failure.status === 404)) {receipt.current.reject();setPending(null);}
        const choices = failure.details.candidates;
        if (code === 'repeated_time' && Array.isArray(choices) && choices.length === 2 && choices.every(item=>typeof item==='string')) {
          setCandidates(choices);setSelected('');setAck(false);
        }
      } else setError('unavailable');
    } finally {controllers.current.delete(controller);setBusy(false);}
  }
  function submit(kind:Command['kind']) {
    const existing = kind === 'confirm' || kind === 'cancel';
    if (existing && !visit) return;
    const command:Command = {...binding,schema_version:'appointments.v1',operation_id:crypto.randomUUID(),
      appointment_id:appointment,expected_revision:visit?.revision ?? 0,kind,
      purpose:existing && visit ? visit.purpose : purpose ?? visit?.purpose ?? 'assessment',
      civil_time:existing && visit ? visit.civil_time : `${date}T${time}`,
      duration_minutes:existing && visit ? visit.duration_minutes : Number(duration),timezone:'Asia/Beirut',
      selected_instant:existing && visit ? visit.instant : selected || null,
      repeated_time_confirmed:existing && visit ? visit.repeated_time_confirmed : Boolean(selected && ack)};
    const attempt = receipt.current.begin(command);setPending(attempt);void perform(attempt);
  }
  function edit(change:()=>void) {change();setCandidates([]);setSelected('');setAck(false);setError('');}
  return <PageFrame><PageHeader title={t.title} lead={t.intro} notice={<p>{t.notice}</p>}/><PageBody>
    {denied ? <State kind="error" title={t.title} body={t.denied}/> : <>
      {read.isFetching && !read.data && known && <State kind="loading" title={t.title} body={t.loading}/>}
      {read.isError && <State kind="error" title={t.errorTitle} body={t.unavailable}><Button onClick={()=>void read.refetch()}>{t.reload}</Button></State>}
      {!visit && !known && <State title={t.title} body={t.empty}/>}
      {visit && <Card><p role="status">{t[visit.state]}</p><p><bdi>{visitTime(visit.instant,locale)}</bdi> · {t[visit.purpose]} · {formatNumber(visit.duration_minutes,locale)} {t.minutes}</p>
        <p>{t.utc}: <bdi>{visit.instant}</bdi></p>
        {visit.state !== 'cancelled' && <>
          {businessStaff && visit.state === 'requested' && <Button disabled={busy || uncertain} onClick={()=>submit('confirm')}>{t.confirm}</Button>}
          <Button variant="outline" disabled={busy || uncertain} onClick={()=>submit('cancel')}>{t.cancel}</Button>
        </>}
      </Card>}
      {!businessStaff && visit?.state !== 'cancelled' && <form onSubmit={event=>{event.preventDefault();submit(visit ? 'reschedule' : 'request');}}>
        <Select label={t.purpose} value={purpose ?? visit?.purpose ?? 'assessment'} disabled={busy || uncertain} onValueChange={value=>edit(()=>setPurpose(value as Purpose))}
          options={(['intake','assessment','fit','collection'] as const).map(value=>({value,label:t[value]}))} messages={messages}/>
        <Input label={t.date} type="date" required value={date} disabled={busy || uncertain} onValueChange={value=>edit(()=>setDate(value))}/>
        <Input label={t.time} hint={t.zone} required value={time} disabled={busy || uncertain} onValueChange={value=>edit(()=>setTime(value))}/>
        <Input label={t.duration} type="number" min={15} max={120} step={1} required value={duration} disabled={busy || uncertain} onValueChange={value=>edit(()=>setDuration(value))}/>
        {candidates.length > 0 && <>
          <Select label={t.utc} value={selected} onValueChange={value=>{setSelected(value);setAck(false);}}
            options={candidates.map(value=>({value,label:value}))} messages={messages}/>
          <Checkbox label={t.repeatedAck} checked={ack} onCheckedChange={setAck}/>
        </>}
        <Button type="submit" disabled={busy || uncertain || Boolean(known && !visit) || (candidates.length > 0 && (!selected || !ack))}>{visit ? t.reschedule : t.request}</Button>
      </form>}
      {error && <State kind="error" title={t.errorTitle} body={errorText}/>}
      {pending && <Card><p role="status">{busy ? t.sending : t.pending}</p><p>{t.reference}: <bdi>{pending.operation_id}</bdi></p>
        <Button disabled={busy} onClick={()=>void perform(pending)}>{t.retry}</Button><Button variant="outline" disabled={busy} onClick={()=>void perform(pending,true)}>{t.lookup}</Button>
      </Card>}
      {visit && !pending && <Button variant="outline" disabled={busy || !known} onClick={()=>{setLocal(null);void read.refetch();}}>{t.reload}</Button>}
    </>}
  </PageBody></PageFrame>;
}
