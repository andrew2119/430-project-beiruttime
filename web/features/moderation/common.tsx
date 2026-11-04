'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { Button, Card } from '@beirut-time/ui';
import en from './en.json';
import ar from './ar.json';
import { operationsRequest } from './api';
import { freshData } from './privacy';

export function useCopy() { const locale=useLocale(); const dictionary:Record<string,string>=locale==='ar'?ar:en; return {locale,t:(key:string)=>dictionary[key]??dictionary.unknownState}; }

export function FeatureFrame({title,intro,children}:{title:string;intro:string;children:React.ReactNode}) {
  const {locale,t}=useCopy();
  return <div className="ops-page"><header className="ops-header"><p className="eyebrow">{t('eyebrow')}</p><h1>{t(title)}</h1><p>{t(intro)}</p><nav aria-label={t('eyebrow')}><Link href={`/${locale}/operations/dashboard`}>{t('dashboard')}</Link><Link href={`/${locale}/operations/moderation`}>{t('moderation')}</Link><Link href={`/${locale}/business-intake`}>{t('intake')}</Link></nav></header>{children}</div>;
}

export function ErrorNotice({error,retry}:{error:unknown;retry?:()=>void}) {
  const {t,locale}=useCopy();
  if(error instanceof ApiError&&error.status===401)return <Card><h2>{t('signIn')}</h2><p>{t('signInBody')}</p><Link className="button" href={`/${locale}/account`}>{t('account')}</Link></Card>;
  const code=error instanceof ApiError?error.code:'unavailable';
  const denied=error instanceof ApiError && error.status===403;
  const known=['independent_review_required','intake_exists','immutable_custody','custody_unconfirmed','custody_scope_mismatch','report_limit','decision_required','idempotency_conflict','invalid_evidence','evidence_limit','evidence_exists','assignment_required'];
  const correction=error instanceof ApiError&&[400,409,422,428,429].includes(error.status);
  const text=code==='stale_revision'?t('stale'):known.includes(code)?t(code):correction?t('invalid'):denied?t('deniedBody'):t('unavailableBody');
  return <div className="ops-notice" role="alert"><strong>{t(denied?'denied':correction?'correctionNeeded':'unavailable')}</strong><p>{text}</p>{error instanceof ApiError&&error.requestId&&<bdi dir="ltr">{error.requestId}</bdi>}{retry&&<Button type="button" className="button-secondary" onClick={retry}>{t('retry')}</Button>}</div>;
}

export function useResource<T>(accessFingerprint:string,service:'trust'|'communications'|'service-operations',path:string,enabled=true) {
  const result=useQuery<T>({
    queryKey:['operations',accessFingerprint,service,path],
    queryFn:({signal})=>operationsRequest<T>(accessFingerprint,service,path,{signal}),
    enabled,retry:false,staleTime:0,refetchOnWindowFocus:false,gcTime:0
  });
  const refetch=result.refetch;
  const refresh=useCallback(()=>{void refetch();},[refetch]);
  return {data:freshData(result),error:result.error,loading:enabled&&(result.isPending||result.isFetching),refresh};
}

export function useCommand() {
  const [state,setState]=useState<{pending:boolean;error?:unknown;saved?:boolean}>({pending:false});
  const active=useRef(false);
  const lifetime=useRef<AbortController|null>(null);
  if(lifetime.current===null)lifetime.current=new AbortController();
  useEffect(()=>{
    if(lifetime.current!.signal.aborted)lifetime.current=new AbortController();
    return ()=>lifetime.current?.abort();
  },[]);
  const requests=useRef(new Map<string,string>());
  const invoke=async<T,>(signature:string,callback:(key:string,signal:AbortSignal)=>Promise<T>):Promise<T|undefined>=>{
    const signal=lifetime.current!.signal;
    if(active.current||signal.aborted) return;
    active.current=true;
    let key=requests.current.get(signature);
    if(!key) {
      key=crypto.randomUUID();
      if(requests.current.size>=20)requests.current.delete(requests.current.keys().next().value!);
      requests.current.set(signature,key);
    }
    setState({pending:true});
    try { const result=await callback(key,signal); if(signal.aborted)return; requests.current.delete(signature); setState({pending:false,saved:true}); return result; }
    catch(error) { if(!signal.aborted)setState({pending:false,error}); return undefined; }
    finally { active.current=false; }
  };
  return {...state,invoke};
}

export function LoadState({loading,error,empty,refresh}:{loading:boolean;error?:unknown;empty?:boolean;refresh:()=>void}) {
  const {t}=useCopy();
  if(loading) return <Card aria-busy="true" role="status">{t('loading')}</Card>;
  if(error) return <ErrorNotice error={error} retry={refresh}/>;
  if(empty) return <Card><h2>{t('empty')}</h2><p>{t('emptyBody')}</p></Card>;
  return null;
}

export function CommandState({pending,error,saved,successKey='saved'}:{pending:boolean;error?:unknown;saved?:boolean;successKey?:string}) {
  const {t}=useCopy();
  return <>{error&&<ErrorNotice error={error}/>}<p className="ops-status" role="status" aria-live="polite">{pending?t('pending'):saved?t(successKey):''}</p></>;
}
