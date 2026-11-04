'use client';
import { useState } from 'react';
import { BidiReference, Button, Card } from '@beirut-time/ui';
import { ApiError } from '@/lib/api/client';
import { mutation, operationsRequest } from './api';
import { CommandState, LoadState, useCommand, useCopy, useResource } from './common';

type Evidence = {id:string;kind:string;media_type:string;size:number};
function asBase64(file:File):Promise<string> {
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>typeof reader.result==='string'?resolve(reader.result.split(',')[1]):reject(new ApiError(422,'invalid_evidence',''));
    reader.onerror=()=>reject(new ApiError(422,'invalid_evidence',''));
    reader.readAsDataURL(file);
  });
}

export default function EvidencePanel({token,id,revision,query,onChange}:{token:string;id:string;revision:number;query:string;onChange:()=>void}) {
  const {t,locale}=useCopy();
  const resource=useResource<{items:Evidence[]}>(token,'service-operations',`intake/records/${id}/evidence${query}`);
  const command=useCommand();
  const [lastAction,setLastAction]=useState<'upload'|'download'>('upload');
  const [file,setFile]=useState<File|null>(null);
  const [kind,setKind]=useState('condition_photo');
  async function upload(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if(!file)return;
    setLastAction('upload');
    const signature=id+':'+revision+':'+kind+':'+file.name+':'+file.size+':'+file.lastModified;
    const result=await command.invoke(signature,async(key,signal)=>{
      if(file.size>262144||file.size<1)throw new ApiError(422,'invalid_evidence','');
      const body={kind,media_type:file.type,content_base64:await asBase64(file)};
      return operationsRequest(token,'service-operations',`intake/records/${id}/evidence${query}`,mutation('POST',key,body,revision,signal));
    });
    if(result){setFile(null);resource.refresh();onChange();}
  }
  async function download(item:Evidence) {
    setLastAction('download');
    await command.invoke('download:'+item.id,async(_key,signal)=>{
      const result=await operationsRequest<{content_base64:string}>(token,'service-operations',`intake/evidence/${item.id}${query}`,{signal});
      if(signal.aborted)return;
      let bytes:Uint8Array<ArrayBuffer>;
      try {
        if(typeof result.content_base64!=='string'||result.content_base64.length>349528)throw new Error('Invalid private file');
        bytes=Uint8Array.from(atob(result.content_base64),character=>character.charCodeAt(0));
      } catch {throw new ApiError(503,'unavailable','');}
      const blob=new Blob([bytes],{type:item.media_type});
      const url=URL.createObjectURL(blob);
      const extension=({'image/jpeg':'jpg','image/png':'png','image/webp':'webp','application/pdf':'pdf'} as Record<string,string>)[item.media_type]??'bin';
      const anchor=document.createElement('a');anchor.href=url;anchor.download='private-intake-'+item.id+'.'+extension;anchor.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      return true;
    });
  }
  return <Card><h2>{t('privateEvidence')}</h2><p className="ops-muted">{t('privateEvidenceHint')}</p><LoadState loading={resource.loading} error={resource.error} refresh={resource.refresh}/><ul className="ops-records">{resource.data?.items.map(item=><li key={item.id}><div><p>{t(item.kind)} · {item.size.toLocaleString(locale)} B</p><BidiReference>{item.id}</BidiReference></div><Button type="button" className="button-secondary" disabled={command.pending} onClick={()=>void download(item)}>{t('downloadPrivate')}</Button></li>)}</ul>
    <form className="ops-form" onSubmit={upload} aria-busy={command.pending}><fieldset className="ops-form-fields" disabled={command.pending}><label>{t('evidenceKind')}<select value={kind} onChange={event=>setKind(event.target.value)}><option value="condition_photo">{t('condition_photo')}</option><option value="prior_owner_record">{t('prior_owner_record')}</option></select></label><label>{t('privateFile')}<input className="input" type="file" required accept="image/jpeg,image/png,image/webp,application/pdf" onChange={event=>setFile(event.target.files?.[0]??null)}/></label><Button type="submit" disabled={!file||command.pending}>{t('attachPrivate')}</Button></fieldset></form><CommandState {...command} successKey={lastAction==='download'?'downloadReady':'saved'}/></Card>;
}
