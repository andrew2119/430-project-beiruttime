'use client';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Button, State } from '@beirut-time/ui/foundation';
import { useLocale } from '@/shell/locale-context';
import { authenticatedRequest } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import en from './en.json';
import ar from './ar.json';
import { isReference } from './submission';

export function useCopy() {
  const locale=useLocale();
  const copy:Record<string,string>=locale==='ar'?ar:en;
  return {locale,t:(key:string)=>copy[key]??copy.unknownState};
}
export function call<T>(scope:string,path:string,options:RequestInit={}) {
  return authenticatedRequest<T>('/api/web/v1/service-operations/v1/'+path,{...options,accessFingerprint:scope});
}
export function Recovery({error,retry}:{error:unknown;retry:()=>void}) {
  const {t}=useCopy();
  const code=error instanceof ApiError?error.status:503;
  const denied=code===401||code===403;
  return <State kind="error" title={t(denied?'denied':'unavailable')} body={t(code===409?'stale':denied?'deniedBody':'unavailableBody')}><Button onClick={retry}>{t('retry')}</Button></State>;
}
export function SupportLink() {
  const {locale,t}=useCopy();
  return <Link className="bt-button bt-pressable" data-variant="outline" href={`/${locale}/inbox`} target="_blank" rel="noopener noreferrer"><span className="bt-button-label">{t('openSupport')}</span></Link>;
}
export type IntakeWriteLock = (locked:boolean, reference?:string, uncertain?:boolean,expectedRevision?:number, orderId?:string)=>void;

function validateIntakeAcknowledgement(result: unknown, path: string, body: unknown, key: string, expectedRevision: number) {
  const [resource, query] = path.split('?');
  const record = /^intake\/records(?:\/([^/]+)(\/evidence)?)?$/.exec(resource);
  const organization = new URLSearchParams(query).get('organization_id');
  if (!record || !organization || !result || typeof result !== 'object') throw new Error('response_scope');

  const answer = result as Record<string, unknown>;
  const [, recordId, evidence] = record;
  const orderId = (body as {order_id?: string}).order_id;
  if (answer.operation_id !== key || answer.organization_id !== organization ||
      !Number.isSafeInteger(answer.revision) || answer.revision !== expectedRevision ||
      !isReference(answer.id) ||
      (evidence ? answer.record_id !== recordId
        : !orderId || answer.order_id !== orderId || (!!recordId && answer.id !== recordId) ||
          (answer.state !== 'awaiting_intake' && answer.state !== 'received'))) {
    throw new Error('response_scope');
  }
}

export function useWrite(scope:string,onDenied?:(error:unknown)=>void,onLockChange?:IntakeWriteLock,closedReference?:string) {
  const [state,setState]=useState<{pending:boolean;error?:unknown;saved?:boolean;reference?:string}>({pending:false});
  const retained=useRef<{signature:string;key:string;expectedRevision:number;orderId?:string}|null>(null);
  const active=useRef(false);
  const life=useRef<AbortController|null>(null);
  useEffect(()=>{life.current=new AbortController();return ()=>life.current?.abort();},[]);
  useEffect(()=>{
    if(!closedReference||retained.current?.key!==closedReference)return;
    retained.current=null;
    setState({pending:false});
  },[closedReference]);
  async function save<T>(path:string,body:unknown,revision?:number,method=revision?'PUT':'POST') {
    const signal=life.current?.signal;
    if(active.current||!signal||signal.aborted)return;
    const signature=JSON.stringify([path,body,revision]);
    if(retained.current&&retained.current.signature!==signature)return;
    const retrying=retained.current!==null;
    retained.current??={signature,key:crypto.randomUUID(),expectedRevision:(revision??0)+1,orderId:(body as {order_id?:string}).order_id};
    const {key,expectedRevision,orderId}=retained.current;
    active.current=true;onLockChange?.(true,key,false,expectedRevision,orderId);setState({pending:true,reference:key});
    try {
      const result=await call<T>(scope,path,{method,signal,headers:{'Content-Type':'application/json','Idempotency-Key':key,...(revision?{'If-Match':String(revision)}:{})},body:JSON.stringify(body)});
      if(signal.aborted||retained.current?.key!==key)return;
      validateIntakeAcknowledgement(result,path,body,key,expectedRevision);
      retained.current=null;setState({pending:false,saved:true});return result;
    } catch(error) {
      if(!signal.aborted&&retained.current?.key===key) {
        const denied=error instanceof ApiError&&[401,403,404].includes(error.status);
        if(!retrying&&error instanceof ApiError&&[400,401,403,404,409,422,428].includes(error.status))retained.current=null;
        if(denied){
          if(!retained.current)onLockChange?.(false);
          onDenied?.(error);
        }
        setState({pending:false,error,reference:retained.current?.key});
      }
    } finally {active.current=false;if(!signal.aborted)onLockChange?.(retained.current!==null,retained.current?.key,retained.current!==null,retained.current?.expectedRevision,retained.current?.orderId);}
  }
  return {...state,save,locked:state.pending||!!state.reference};
}
