'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { BidiReference, Button, Card, Input } from '@beirut-time/ui';
import { operationsRequest, mutation, type CaseDetail, type CaseSummary } from './api';
import { CommandState, FeatureFrame, LoadState, useCommand, useCopy, useResource } from './common';
import { reportChoices, saveReportChoices } from './drafts';

export default function ModerationScreen({token,initialCase=''}:{token:string;initialCase?:string}) {
  const {t,locale}=useCopy();
  const router=useRouter();
  const [offset,setOffset]=useState(0);
  const queue=useResource<{items:CaseSummary[];next_offset:number|null}>(token,'trust',`moderation/cases?offset=${offset}`);
  const [selected,setSelected]=useState(initialCase);
  const [sequence,setSequence]=useState(0);
  const [reference,setReference]=useState(initialCase);
  const [releasing,setReleasing]=useState<CaseSummary|null>(null);
  const [releaseReason,setReleaseReason]=useState('');
  const [report,setReport]=useState(()=>({...reportChoices(token),evidence:''}));
  const command=useCommand();
  const {target_kind,target_id,category}=report;
  useEffect(()=>saveReportChoices(token,{target_kind,target_id,category}),[token,target_kind,target_id,category]);
  function chooseCase(id:string) {
    setSelected(id);setReference(id);setSequence(value=>value+1);
    router.replace(`/${locale}/operations/moderation?case=${encodeURIComponent(id)}`,{scroll:false});
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault();
    const result=await command.invoke(JSON.stringify(report),(key,signal)=>operationsRequest<{id:string}>(token,'trust','moderation/reports',mutation('POST',key,report,undefined,signal)));
    if(result) { chooseCase(result.id);setReport({...report,evidence:''});setOffset(0);queue.refresh(); }
  }
  async function claim(row:CaseSummary) {
    const result=await command.invoke('claim:'+row.id+':'+row.revision,(key,signal)=>operationsRequest(token,'trust',`moderation/cases/${row.id}/claim`,mutation('POST',key,undefined,row.revision,signal)));
    if(result) {chooseCase(row.id);queue.refresh();}
  }
  async function release(event:React.FormEvent) {
    event.preventDefault();if(!releasing)return;
    const body={reason:releaseReason};
    const result=await command.invoke('release:'+releasing.id+':'+releasing.revision+JSON.stringify(body),(key,signal)=>operationsRequest(token,'trust',`moderation/cases/${releasing.id}/release`,mutation('POST',key,body,releasing.revision,signal)));
    if(result) {
      if(selected===releasing.id){setSelected('');setReference('');router.replace(`/${locale}/operations/moderation`,{scroll:false});}
      setReleasing(null);setReleaseReason('');queue.refresh();
    }
  }
  return <FeatureFrame title="moderation" intro="moderationIntro"><div className="ops-columns"><div className="ops-stack"><Card><h2>{t('report')}</h2><form className="ops-form" onSubmit={submit} aria-busy={command.pending}><fieldset className="ops-form-fields" disabled={command.pending}>
    <label>{t('targetKind')}<select value={report.target_kind} onChange={e=>setReport({...report,target_kind:e.target.value})}>{['listing','user','message'].map(kind=><option key={kind} value={kind}>{t(kind)}</option>)}</select></label>
    <label>{t('targetId')}<Input dir="ltr" required maxLength={36} pattern="[0-9a-fA-F-]{36}" value={report.target_id} onChange={e=>setReport({...report,target_id:e.target.value})}/></label>
    <label>{t('category')}<select value={report.category} onChange={e=>setReport({...report,category:e.target.value})}>{['counterfeit','misleading','harassment','payment_abuse','other'].map(reason=><option key={reason} value={reason}>{t(reason)}</option>)}</select></label>
    <label>{t('evidence')}<textarea required maxLength={4000} rows={5} value={report.evidence} onChange={e=>setReport({...report,evidence:e.target.value})} aria-describedby="evidence-hint"/></label><p id="evidence-hint" className="ops-muted">{t('evidenceHint')}</p>
    <Button disabled={command.pending} type="submit">{t('submitReport')}</Button></fieldset></form></Card>
    <Card><h2>{t('queue')}</h2><p className="ops-muted">{t('claimHint')}</p><Button className="button-secondary" type="button" onClick={queue.refresh}>{t('refresh')}</Button><LoadState loading={queue.loading} error={queue.error} empty={queue.data?.items.length===0} refresh={queue.refresh}/>
    <ul className="ops-records">{queue.data?.items.map(row=><li key={row.id}><div><BidiReference>{row.id}</BidiReference><p>{t(row.target_kind)} · {t(row.status)} · {t('revision')} {row.revision}</p></div><div className="ops-actions">{row.can_claim!==false&&<Button type="button" disabled={command.pending} onClick={()=>row.assigned_to?chooseCase(row.id):void claim(row)}>{t(row.assigned_to?'openCase':'claim')}</Button>}{row.can_release&&<Button type="button" className="button-secondary" disabled={command.pending} onClick={()=>setReleasing(row)}>{t('release')}</Button>}</div></li>)}</ul>
    <div className="ops-actions">{offset>0&&<Button type="button" className="button-secondary" onClick={()=>setOffset(value=>Math.max(0,value-50))}>{t('previousPage')}</Button>}{queue.data?.next_offset!=null&&queue.data.next_offset<=10000&&<Button type="button" className="button-secondary" onClick={()=>setOffset(queue.data!.next_offset!)}>{t('nextPage')}</Button>}</div>
    {releasing&&<form className="ops-form" onSubmit={release}><fieldset className="ops-form-fields" disabled={command.pending}><h3>{t('release')}</h3><BidiReference>{releasing.id}</BidiReference><label>{t('releaseReason')}<textarea required minLength={3} maxLength={4000} rows={3} value={releaseReason} onChange={event=>setReleaseReason(event.target.value)}/></label><Button type="submit">{t('confirmRelease')}</Button></fieldset></form>}</Card>
    <Card><form className="ops-form" onSubmit={e=>{e.preventDefault();chooseCase(reference);}}><label>{t('caseReference')}<Input dir="ltr" required pattern="[0-9a-fA-F-]{36}" maxLength={36} value={reference} onChange={e=>setReference(e.target.value)}/></label><Button type="submit">{t('openCase')}</Button></form></Card><CommandState {...command}/></div>
    <div className="ops-stack">{selected?<CasePanel key={`${selected}:${sequence}`} token={token} id={selected} onChange={queue.refresh}/>:<Card><h2>{t('decision')}</h2><p>{t('claimHint')}</p><p className="ops-policy">{t('duties')}</p></Card>}</div></div></FeatureFrame>;
}

function CasePanel({token,id,onChange}:{token:string;id:string;onChange:()=>void}) {
  const {t,locale}=useCopy();
  const [auditBefore,setAuditBefore]=useState<number|null>(null);
  const resource=useResource<CaseDetail>(token,'trust',`moderation/cases/${id}`+(auditBefore?`?before_revision=${auditBefore}`:''));
  const decision=useCommand();
  const appeal=useCommand();
  const [action,setAction]=useState('warn');
  const [reason,setReason]=useState('');
  const [appealReason,setAppealReason]=useState('');
  const data=resource.data;
  async function submit(event:React.FormEvent) {
    event.preventDefault(); if(!data)return;
    const body={action,reason};
    const result=await decision.invoke(id+':'+data.revision+JSON.stringify(body),(key,signal)=>operationsRequest(token,'trust',`moderation/cases/${id}/decisions`,mutation('POST',key,body,data.revision,signal)));
    if(result) {setReason('');setAuditBefore(null);resource.refresh();onChange();}
  }
  async function submitAppeal(event:React.FormEvent) {
    event.preventDefault();if(!data)return;
    const body={reason:appealReason};
    const result=await appeal.invoke(id+':'+data.revision+JSON.stringify(body),(key,signal)=>operationsRequest(token,'trust',`moderation/cases/${id}/appeals`,mutation('POST',key,body,data.revision,signal)));
    if(result) {setAppealReason('');setAuditBefore(null);resource.refresh();onChange();}
  }
  return <><LoadState loading={resource.loading} error={resource.error} refresh={resource.refresh}/>{data&&<Card><div className="ops-card-heading"><h2>{t('caseReference')}</h2><Button className="button-secondary" type="button" onClick={resource.refresh}>{t('refresh')}</Button></div><BidiReference>{data.id}</BidiReference><p><span className="ops-badge">{t(data.status)}</span> · {t('revision')} {new Intl.NumberFormat(locale).format(data.revision)}</p>
    {data.evidence&&<section className="ops-private"><h3>{t('evidence')}</h3><p>{data.evidence}</p></section>}{data.review_signals.length>0&&<section className="ops-private"><h3>{t('reviewSignals')}</h3><ul>{data.review_signals.map(signal=><li key={signal}>{t(signal)}</li>)}</ul></section>}<p className="ops-policy">{t('duties')}</p><Link className="button button-secondary" href={`/${locale}/inbox`}>{t('support')}</Link>
    {data.delivery!=='none'&&<p role="status">{t(data.delivery==='acknowledged'?'deliveryAcknowledged':'deliveryPending')}</p>}
    {data.can_decide&&<form className="ops-form" onSubmit={submit} aria-busy={decision.pending}><fieldset className="ops-form-fields" disabled={decision.pending}><h3>{t('decision')}</h3><label>{t('action')}<select value={action} onChange={e=>setAction(e.target.value)}>{['warn',...(data.target_kind==='user'?['suspend']:['hide']),'reinstate','dismiss'].map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label><label>{t('reason')}<textarea required minLength={3} maxLength={4000} rows={4} value={reason} onChange={e=>setReason(e.target.value)}/></label><Button type="submit" disabled={decision.pending}>{t('saveDecision')}</Button><CommandState {...decision}/></fieldset></form>}
    {data.can_appeal&&<form className="ops-form" onSubmit={submitAppeal} aria-busy={appeal.pending}><fieldset className="ops-form-fields" disabled={appeal.pending}><h3>{t('appeal')}</h3><label>{t('appealReason')}<textarea required minLength={3} maxLength={4000} rows={4} value={appealReason} onChange={e=>setAppealReason(e.target.value)}/></label><Button type="submit" disabled={appeal.pending}>{t('submitAppeal')}</Button><CommandState {...appeal}/></fieldset></form>}
    <h3>{t('history')}</h3><ol className="ops-audit">{data.audit.map(item=><li key={item.revision}><strong>{t(item.kind)}</strong><p>{item.kind==='claim'?t('independentAssigned'):item.reason}</p><time dateTime={item.created_at}>{new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Beirut'}).format(new Date(item.created_at))}</time></li>)}</ol><div className="ops-actions">{data.audit_older_available&&data.audit[0]&&<Button type="button" className="button-secondary" onClick={()=>setAuditBefore(data.audit[0].revision)}>{t('olderHistory')}</Button>}{auditBefore&&<Button type="button" className="button-secondary" onClick={()=>setAuditBefore(null)}>{t('latestHistory')}</Button>}</div></Card>}</>;
}
