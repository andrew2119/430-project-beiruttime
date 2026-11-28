'use client';
import { useEffect, useId, useRef, useState } from 'react';
import { Button, Card, Checkbox, Label, Select, State, formatNumber } from '@beirut-time/ui/foundation';
import { definePageRead } from '@/lib/page-speed/definition';
import { privateRecordUnavailable } from '../private-read';
import type { IntakeRead } from './mounted-read';
import { usePageRead } from '@/lib/page-speed/read';
import { call, Recovery, useCopy, useWrite, type IntakeWriteLock } from '../common';

type Evidence={id:string;kind:string;media_type:string;size:number};
const evidenceRead=definePageRead({key:(scope:string,organization:string,id:string,generation:string)=>['maintenance-evidence',scope,organization,id,generation],warm:'open-only',fresh:0,
  ask:(signal:AbortSignal,scope:string,organization:string,id:string)=>call<{items:Evidence[]}>(scope,`intake/records/${id}/evidence?organization_id=${encodeURIComponent(organization)}`,{signal})});
function content(file:File):Promise<string> {
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>typeof reader.result==='string'?resolve(reader.result.split(',')[1]):reject(new Error('invalid_file'));reader.onerror=()=>reject(new Error('invalid_file'));reader.readAsDataURL(file);});
}
export default function EvidencePanel({useRead=usePageRead,readGeneration='',closedReference,scope,organization,id,revision,changed,onDenied,onLockChange,readOnly=false}:{useRead?:IntakeRead;readGeneration?:string;closedReference?:string;onLockChange?:IntakeWriteLock;scope:string;organization:string;id:string;revision:number;readOnly?:boolean;changed:()=>void;onDenied:(error:unknown)=>void}) {
  const {t,locale}=useCopy();const fieldId=useId();const command=useWrite(scope,onDenied,onLockChange,closedReference);
  const read=useRead(evidenceRead(scope,organization,id,readGeneration));
  useEffect(()=>{if(privateRecordUnavailable(read.error))onDenied(read.error);},[read.error,onDenied]);
  const fileInput=useRef<HTMLInputElement>(null);
  const selection = useRef(0);
  const preparing = useRef(false);
  const retainedRevision=useRef<number|undefined>(undefined);
  const [safe,setSafe]=useState(false);
  const [file,setFile]=useState<File|null>(null);const [kind,setKind]=useState('condition_photo');const [invalid,setInvalid]=useState(false);const [downloadError,setDownloadError]=useState<{error:unknown;item:Evidence}>();
  const lifetime=useRef<AbortController|null>(null);
  useEffect(()=>{lifetime.current=new AbortController();return ()=>lifetime.current?.abort();},[]);
  useEffect(()=>{if(command.error&&!command.reference)retainedRevision.current=undefined;},[command.error,command.reference]);
  useEffect(()=>{
    if(closedReference&&command.reference===closedReference)retainedRevision.current=undefined;
  },[closedReference,command.reference]);
  const query='?organization_id='+encodeURIComponent(organization);
  async function upload() {
    const signal = lifetime.current?.signal;
    if (!file || readOnly || preparing.current || !signal || signal.aborted) return;
    if(file.type.startsWith('image/')&&!safe){setInvalid(true);return;}
    if(file.size<1||file.size>262144||!['image/jpeg','image/png','image/webp','application/pdf'].includes(file.type)){setInvalid(true);return;}
    const selected = selection.current;
    preparing.current = true;
    try {
      const bytes = await content(file);
      if (signal.aborted || selected !== selection.current) return;
      retainedRevision.current??=revision;
      const result=await command.save(`intake/records/${id}/evidence${query}`,{kind,safe_photo_declared:safe,media_type:file.type,content_base64:bytes},retainedRevision.current,'POST');
      if(result && !signal.aborted && selected === selection.current){retainedRevision.current=undefined;setFile(null);setSafe(false);setInvalid(false);if(fileInput.current)fileInput.current.value='';void read.refetch();changed();}
    } catch {
      if (!signal.aborted && selected === selection.current) setInvalid(true);
    } finally {
      preparing.current = false;
    }
  }
  async function download(item:Evidence) {
    setDownloadError(undefined);
    try {
      const signal=lifetime.current?.signal;if(!signal||signal.aborted)return;
      const result=await call<{content_base64:string}>(scope,`intake/evidence/${item.id}${query}`,{signal});
      if(signal.aborted)return;
      if(typeof result.content_base64!=='string'||result.content_base64.length>349528)throw new Error('invalid_file');
      const bytes=Uint8Array.from(atob(result.content_base64),c=>c.charCodeAt(0));
      const url=URL.createObjectURL(new Blob([bytes],{type:item.media_type}));const link=document.createElement('a');
      link.href=url;link.download='private-intake-'+item.id;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(error) {if(lifetime.current?.signal.aborted)return;if(privateRecordUnavailable(error)){setFile(null);onDenied(error);return;}setDownloadError({error,item});}
  }
  if(privateRecordUnavailable(read.error))return <Recovery error={read.error} retry={()=>void read.refetch()}/>;
  const messages={placeholder:t('evidenceKind'),filter:t('evidenceKind'),emptyTitle:t('empty'),emptyBody:t('emptyBody'),close:t('close'),loading:t('loading'),errorTitle:t('unavailable'),errorBody:t('unavailableBody'),retry:t('retry')};
  return <Card><h2>{t('privateEvidence')}</h2><p>{t('filesLimit')}</p>{!!read.error&&<Recovery error={read.error} retry={()=>void read.refetch()}/>} {read.isPending&&<p role="status">{t('loading')}</p>}{read.data&&!privateRecordUnavailable(read.error)&&(read.data.items.length===0?<State title={t('empty')} body={t('emptyBody')}/>:<ul>{read.data!.items.map(item=><li key={item.id}><p>{t(item.kind)} · {formatNumber(item.size,locale)} B</p><Button onClick={()=>void download(item)}>{t('downloadPrivate')}</Button></li>)}</ul>)}
    <form onSubmit={event=>{event.preventDefault();void upload();}}><fieldset disabled={command.locked||readOnly}>
      <Select label={t('evidenceKind')} value={kind} onValueChange={value=>{selection.current++;setKind(value);}} options={['condition_photo','prior_owner_record'].map(value=>({value,label:t(value)}))} messages={messages}/>
      <Label htmlFor={fieldId}>{t('privateFile')}</Label><input ref={fileInput} className="bt-input" id={fieldId} type="file" required accept="image/jpeg,image/png,image/webp,application/pdf" onChange={event=>{selection.current++;setFile(event.target.files?.[0]??null);setSafe(false);setInvalid(false);}}/>
      <Checkbox label={t('safePhoto')} checked={safe} onCheckedChange={value=>{selection.current++;setSafe(value);}}/><Button type="submit" disabled={!file}>{t('attachPrivate')}</Button></fieldset></form>
    {invalid&&<p role="alert">{t('filesLimit')}</p>}{!!command.error&&<Recovery error={command.error} retry={()=>void upload()}/>}<p role="status">{command.pending?t('pending'):command.saved?t('saved'):command.reference?t('retrySame'):''}</p>{command.reference&&<bdi>{command.reference}</bdi>}{!!downloadError&&<Recovery error={downloadError.error} retry={()=>void download(downloadError.item)}/>}</Card>;
}
