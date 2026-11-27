'use client';
import { useState } from 'react';
import { useBusinessRead } from './reads';
import { Button, Card, Checkbox, Input, formatNumber, State } from '@beirut-time/ui/foundation';
import type { StaffMember, StaffWorkspace } from '@contracts/contracts-identity/businesses/workspace_v2';
import { useAccessContext } from '@/shell/access-context';
import { businessRequest } from './transport';
import { BusinessLoading, Feedback, Select, text, useCopy, Workspace, capabilityLabel } from './components';
import { PlatformMemberships } from './platform-membership';
import { accessDenied, PendingRecovery, CommandForm, useCommandSnapshot, usePendingCommands, type PendingChange } from './command-form';
import { useLocale } from '@/shell/locale-context';
const ordinary = ['business.stock.write', 'business.jobs.write', 'business.records.read'];

export function StaffEditor({ data, member, refresh, busy=false, onPending }: {data: StaffWorkspace; member?: StaffMember; refresh: () => void; busy?: boolean; onPending?: PendingChange}) {
  const t = useCopy();
  const [permissions, setPermissions] = useState(member?.permissions ?? []);
  return <Card>
    <h2>{member ? <bdi>{member.subject_id}</bdi> : t.grantAction}</h2>
    {member && <p>{t[member.state]} · {t.revision} {member.revision}</p>}
    <CommandForm disabled={busy} onPending={onPending} onComplete={refresh} submit={(form, operation) => {
      const replacement = data.replacements.find(item => item.subject_id === text(form, 'replacement'));
      return operation.send('/v2/business-staff/commands', {
        actor_id: data.actor_id, subject_id: member?.subject_id ?? text(form, 'subject'),
        organization_id: data.organization_id, expected_revision: member?.revision ?? 0,
        kind: text(form, 'kind'), permissions: permissions.filter(permission => ordinary.includes(permission) && data.ceiling.includes(permission)), reason: text(form, 'reason'),
        ceiling_revision: data.ceiling_revision,
        job_revisions: Object.fromEntries(data.jobs.map(job => [job.job_id, job.revision])),
        replacement_id: replacement?.subject_id ?? null, replacement_revision: replacement?.revision ?? null,
      });
    }}>
      {!member && <Input name="subject" label={t.subjectId} required />}
      <Select name="kind" label={t.decision} options={[
        {value:'grant',label:t.grantAction}, ...(member ? [{value:'suspend',label:t.suspend},{value:'remove',label:t.remove}] : []),
      ]} />
      {ordinary.filter(permission => data.ceiling.includes(permission)).map(permission => <Checkbox key={permission}
        label={capabilityLabel(permission,t)} checked={permissions.includes(permission)}
        onCheckedChange={checked => setPermissions(values => checked ? [...values,permission] : values.filter(value => value !== permission))} />)}
      <Select name="replacement" label={t.replacement} options={[
        {value:'',label:t.noReplacement}, ...data.replacements.filter(item => item.subject_id !== member?.subject_id).map(item => ({value:item.subject_id,label:item.subject_id})),
      ]} />
      <Input name="reason" label={t.reason} required />
    </CommandForm>
  </Card>;
}
export default function Memberships() {
  const t = useCopy(), locale = useLocale(), access = useAccessContext();
  const [business, setBusiness] = useState(''), [page, setPage] = useState(1);
  const {busy, onPending: setBusy, recovery} = usePendingCommands();
  const query = useBusinessRead({
    queryKey: ['business-v2','staff',access.fingerprint,business,page],
    queryFn: () => businessRequest<StaffWorkspace>(`/v2/business-staff/workspaces/${encodeURIComponent(business)}?page=${page}&page_size=25`),
    enabled: !!business, retry: false,
  });
  const data = useCommandSnapshot(
    query.isError || query.data?.organization_id !== business ? undefined : query.data,
    busy, access.fingerprint, accessDenied(query.error),
  );
  return <Workspace title={t.membership} intro={t.staffHelp}>
    <Card><form className="business-form" onSubmit={event => {
      event.preventDefault(); if (busy) return; setPage(1); setBusiness(text(new FormData(event.currentTarget),'business'));
    }}><Input name="business" label={t.businessId} required /><Button type="submit" disabled={busy}>{t.open}</Button></form></Card>
    {business && <Button disabled={busy} onClick={() => void query.refetch()}>{t.reload}</Button>}
    {business && query.isPending && <BusinessLoading />}
    <Feedback error={query.error} />
    {busy && !data ? <PendingRecovery recovery={recovery} onPending={setBusy} refresh={() => void query.refetch()} /> : null}
    {data && <>
      <p>{t.serverTotal}: {formatNumber(data.total,locale)}</p>
      <p>{t.ceiling}: {data.ceiling.map(permission => capabilityLabel(permission,t)).join(' · ')}</p>
      <p>{t.replacementHelp}</p>
      {data.jobs.map(job => <p key={job.job_id}><bdi>{job.job_id}</bdi> · {t.responsible}: <bdi>{job.responsible_id}</bdi> · {t.revision} {job.revision}</p>)}
      {!data.can_manage ? <State title={t.forbidden} body={t.noAuthority} /> : !data.responsibilities_current ? <State kind="error" title={t.unavailable} body={t.replacementHelp} /> : <>
        <StaffEditor key={`${business}:new:${data.ceiling_revision}`} data={data} busy={busy} onPending={setBusy} refresh={() => void query.refetch()} />
        {data.items.filter(member => member.ordinary && member.subject_id !== data.actor_id).map(member => <StaffEditor
          key={`${business}:${member.subject_id}:${member.revision}:${data.ceiling_revision}`} data={data} member={member} busy={busy} onPending={setBusy} refresh={() => void query.refetch()} />)}
      </>}
      {data.items.length === 0 && <State title={t.noMembers} body="" />}
      <Button disabled={busy || page <= 1} onClick={() => setPage(value => value-1)}>{t.previous}</Button>
      <Button disabled={busy || page * data.page_size >= data.total} onClick={() => setPage(value => value+1)}>{t.next}</Button>
    </>}
    <PlatformMemberships />
  </Workspace>;
}
