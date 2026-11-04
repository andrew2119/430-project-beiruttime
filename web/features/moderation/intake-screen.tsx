'use client';
import { useEffect, useState } from 'react';
import { normalizeDigits } from '@beirut-time/i18n';
import { BidiReference, Button, Card, Input } from '@beirut-time/ui';
import { operationsRequest, mutation, type IntakeBody, type IntakeDetail, type IntakeSummary } from './api';
import { CommandState, FeatureFrame, LoadState, useCommand, useCopy, useResource } from './common';
import EvidencePanel from './evidence-panel';
import { currencyChoice, intakeSelection, organizationChoice, saveCurrencyChoice, saveIntakeSelection, saveOrganizationChoice } from './drafts';

const initial:IntakeBody={order_id:'',custody_receipt_id:null,serial:'',reference:'',movement:'',received_condition:'',accessories:'',reported_issue:'',assessed_issue:'',diagnostic_opening_permission:false,no_polish_acknowledged:false,fee_acknowledged:false,fee_minor:0,currency:'USD'};
const textFields=['serial','reference','movement','received_condition','accessories','reported_issue','assessed_issue'] as const;
const checkFields=['diagnostic_opening_permission','no_polish_acknowledged','fee_acknowledged'] as const;

export default function IntakeScreen({token,organizations}:{token:string;organizations:string[]}) {
  const {t}=useCopy();
  const [organizationId,setOrganizationId]=useState(()=>organizationChoice(token,organizations));
  useEffect(()=>saveOrganizationChoice(token,organizationId),[token,organizationId]);
  return <FeatureFrame title="intake" intro="intakeIntro"><Card><label className="ops-form">{t('organization')}<select dir="ltr" value={organizationId} onChange={event=>setOrganizationId(event.target.value)}><option value="">{t('chooseOrganization')}</option>{organizations.map(id=><option key={id} value={id}>{id}</option>)}</select></label></Card>{organizationId?<OrganizationIntake key={organizationId} token={token} organizationId={organizationId}/>:<Card><p>{t('chooseOrganization')}</p></Card>}</FeatureFrame>;
}

function OrganizationIntake({token,organizationId}:{token:string;organizationId:string}) {
  const {t}=useCopy();
  const query='?organization_id='+encodeURIComponent(organizationId);
  const [offset,setOffset]=useState(0);
  const records=useResource<{items:IntakeSummary[];next_offset:number|null}>(token,'service-operations','intake/records'+query+'&offset='+offset);
  const [selected,setSelected]=useState<string|null>(()=>intakeSelection(token,organizationId));
  useEffect(()=>saveIntakeSelection(token,organizationId,selected),[token,organizationId,selected]);
  const [sequence,setSequence]=useState(0);
  return <><p className="ops-policy">{t('noPass')}</p><div className="ops-columns"><div className="ops-stack"><Card><div className="ops-card-heading"><h2>{t('queue')}</h2><Button type="button" className="button-secondary" onClick={records.refresh}>{t('refresh')}</Button></div><Button type="button" onClick={()=>{setSelected(null);setSequence(v=>v+1);}}>{t('newIntake')}</Button><LoadState loading={records.loading} error={records.error} empty={records.data?.items.length===0} refresh={records.refresh}/><ul className="ops-records">{records.data?.items.map(record=><li key={record.id}><div><BidiReference>{record.order_id}</BidiReference><p><span className="ops-badge">{t(record.state)}</span> · {t('revision')} {record.revision}</p></div><Button type="button" className="button-secondary" onClick={()=>{setSelected(record.id);setSequence(value=>value+1);records.refresh();}}>{t('open')}</Button></li>)}</ul><div className="ops-actions">{offset>0&&<Button type="button" className="button-secondary" onClick={()=>setOffset(value=>Math.max(0,value-50))}>{t('previousPage')}</Button>}{records.data?.next_offset!=null&&records.data.next_offset<=10000&&<Button type="button" className="button-secondary" onClick={()=>setOffset(records.data!.next_offset!)}>{t('nextPage')}</Button>}</div></Card></div>
  <IntakeEditor key={`${selected??'new'}:${sequence}`} token={token} query={query} id={selected} onSave={id=>{setSelected(id);setOffset(0);records.refresh();}}/></div></>;
}

function IntakeEditor({token,id,query,onSave}:{token:string;id:string|null;query:string;onSave:(id:string)=>void}) {
  const {t}=useCopy();
  const resource=useResource<IntakeDetail>(token,'service-operations',(id?`intake/records/${id}`:'intake/records')+query,id!==null);
  const data=id?resource.data:undefined;
  const refresh=()=>{resource.refresh();if(id)onSave(id);};
  return <div className="ops-stack">{id&&<div className="ops-toolbar"><Button type="button" className="button-secondary" disabled={resource.loading} onClick={refresh}>{t('refresh')}</Button></div>}
    {id&&(resource.loading||resource.error)?<LoadState loading={resource.loading} error={resource.error} refresh={refresh}/>:<IntakeForm key={`${id??'new'}:${data?.revision??0}`} token={token} query={query} id={id} data={data} onSave={savedId=>{if(id)resource.refresh();onSave(savedId);}}/>}
    {id&&data&&<EvidencePanel token={token} id={id} revision={data.revision} query={query} onChange={refresh}/>}</div>;
}

function IntakeForm({token,id,data,query,onSave}:{token:string;id:string|null;data?:IntakeDetail;query:string;onSave:(id:string)=>void}) {
  const {t,locale}=useCopy();
  const [form,setForm]=useState<IntakeBody>(data?{...data.private_record,order_id:data.order_id,custody_receipt_id:data.custody_receipt_id}:{...initial,currency:currencyChoice(token)});
  const [fee,setFee]=useState(String(data?.private_record.fee_minor??0));
  const currency=form.currency;
  useEffect(()=>saveCurrencyChoice(token,currency),[token,currency]);
  const command=useCommand();
  async function save(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized=normalizeDigits(fee);
    if(!/^\d{1,12}$/.test(normalized))return;
    const body={...form,fee_minor:Number(normalized)};
    const result=await command.invoke((id??'new')+':'+(data?.revision??0)+JSON.stringify(body),(key,signal)=>operationsRequest<{id:string}>(token,'service-operations',(id?`intake/records/${id}`:'intake/records')+query,mutation(id?'PUT':'POST',key,body,data?.revision,signal)));
    if(result) onSave(result.id);
  }
  return <Card><h2>{t(id?'intake':'newIntake')}</h2>{data&&<><BidiReference>{data.id}</BidiReference><p className="ops-muted">{t('revision')} {new Intl.NumberFormat(locale).format(data.revision)}</p><p className="ops-badge">{t(data.state)}</p><p>{t(data.diagnosis_allowed?'diagnosisAllowed':'diagnosisNotAllowed')}</p>{data.state==='received'&&data.custody_verification!=='current'&&<p className="ops-policy">{t('custodyNotCurrent')}</p>}</>}
    <form className="ops-form" onSubmit={save} autoComplete="off" aria-busy={command.pending}><fieldset className="ops-form-fields" disabled={command.pending}><label>{t('order_id')}<Input dir="ltr" required readOnly={!!id} maxLength={36} pattern="[0-9a-fA-F-]{36}" value={form.order_id} onChange={e=>setForm({...form,order_id:e.target.value})}/></label><label>{t('custody_receipt_id')}<Input dir="ltr" maxLength={36} pattern="[0-9a-fA-F-]{36}" readOnly={!!data?.custody_receipt_id} value={form.custody_receipt_id??''} onChange={e=>setForm({...form,custody_receipt_id:e.target.value||null})}/></label><p className="ops-muted">{t('custodyHint')}</p>
    <div className="ops-field-grid">{textFields.map(field=><label key={field}>{t(field)}{['serial','reference','movement'].includes(field)?<Input required dir={field==='movement'?undefined:'ltr'} maxLength={160} value={form[field]} onChange={e=>setForm({...form,[field]:e.target.value})}/>:<textarea required={['received_condition','reported_issue'].includes(field)} maxLength={2000} rows={3} value={form[field]} onChange={e=>setForm({...form,[field]:e.target.value})}/>}</label>)}</div>
    <fieldset className="ops-checks">{checkFields.map(field=><label key={field}><input type="checkbox" checked={form[field]} onChange={e=>setForm({...form,[field]:e.target.checked})}/><span>{t(field)}</span></label>)}</fieldset>
    <div className="ops-field-grid"><label>{t('fee_minor')}<Input required inputMode="numeric" pattern="[0-9٠-٩۰-۹]{1,12}" value={fee} onChange={e=>setFee(e.target.value)}/></label><label>{t('currency')}<select dir="ltr" value={form.currency} onChange={e=>setForm({...form,currency:e.target.value as 'USD'|'LBP'})}><option value="USD">USD</option><option value="LBP">LBP</option></select></label></div><p className="ops-muted">{t('feeHint')}</p><Button type="submit" disabled={command.pending}>{t('saveIntake')}</Button><CommandState {...command}/></fieldset></form></Card>;
}
