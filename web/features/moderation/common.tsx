'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { LayoutDashboard, ShieldCheck, Wrench } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';
import { useSession } from '@/features/identity/session';
import { PageHeader, PageLayout, type HeaderAction } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { ApiError } from '@/lib/api/client';
import { Button, ButtonLink, HeaderTabs, Skeleton, State } from '@beirut-time/ui';
import en from './en.json';
import ar from './ar.json';
import { operationsRequest } from './api';
import { freshData } from './privacy';

export function useCopy() { const locale=useLocale(); const dictionary:Record<string,string>=locale==='ar'?ar:en; return {locale,t:(key:string)=>dictionary[key]??dictionary.unknownState}; }

export function FeatureFrame({title,intro,children,actions}:{title:string;intro:string;children:React.ReactNode;actions?:HeaderAction[]}) {
  const {locale,t}=useCopy();
  const pathname=usePathname().replace(/^\/(en|ar)(?=\/|$)/,'');
  const router=useRouter();
  const roles=useSession()?.principal.roles??[];
  const entries=[{id:'/operations/dashboard',key:'dashboard',roles:['operator'],icon:LayoutDashboard},{id:'/operations/moderation',key:'moderation',roles:['operator'],icon:ShieldCheck},{id:'/business-intake',key:'intake',roles:['brand','dealer'],icon:Wrench}];
  const visibleEntries=entries.filter(item=>item.roles.some(role=>roles.includes(role))).map(item=>({...item,label:t(item.key),href:`/${locale}${item.id}`}));
  const active=visibleEntries.find(item=>pathname===item.id||pathname.startsWith(item.id+'/'))?.id??pathname;
  return <PageLayout className="ops-page"><PageHeader title={t(title)} count={t(intro)} actions={actions} lead={<p className="ops-muted">{t('eyebrow')}</p>}
    nav={visibleEntries.length?<HeaderTabs nav label={t('eyebrow')} items={visibleEntries} value={active} onChange={id=>router.push(`/${locale}${id}`)}/>:undefined}/><div className="ops-content">{children}</div></PageLayout>;
}

export function ErrorNotice({error,retry}:{error:unknown;retry?:()=>void}) {
  const {t,locale}=useCopy();
  if(error instanceof ApiError&&error.status===401)return <State title={t('signIn')} body={t('signInBody')}><ButtonLink href={`/${locale}/account`}>{t('account')}</ButtonLink></State>;
  const code=error instanceof ApiError?error.code:'unavailable';
  const denied=error instanceof ApiError && error.status===403;
  const known=['independent_review_required','intake_exists','immutable_custody','custody_unconfirmed','custody_scope_mismatch','report_limit','decision_required','idempotency_conflict','invalid_evidence','evidence_limit','evidence_exists','assignment_required'];
  const correction=error instanceof ApiError&&[400,409,422,428,429].includes(error.status);
  const text=code==='stale_revision'?t('stale'):known.includes(code)?t(code):correction?t('invalid'):denied?t('deniedBody'):t('unavailableBody');
  return <div className="ops-notice" role="alert"><State kind="error" title={t(denied?'denied':correction?'correctionNeeded':'unavailable')} body={text}>{error instanceof ApiError&&error.requestId&&<bdi dir="ltr">{error.requestId}</bdi>}{retry&&<Button chonk type="button" variant="outline" onClick={retry}>{t('retry')}</Button>}</State></div>;
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
  if(loading) return <div className="ops-loading" aria-busy="true" role="status" aria-label={t('loading')}><span className="sr-only">{t('loading')}</span>{[0,1,2].map(row=><Skeleton key={row} className="ops-row-skeleton"/>)}</div>;
  if(error) return <ErrorNotice error={error} retry={refresh}/>;
  if(empty) return <State title={t('empty')} body={t('emptyBody')}/>;
  return null;
}

export function CommandState({pending,error,saved,successKey='saved'}:{pending:boolean;error?:unknown;saved?:boolean;successKey?:string}) {
  const {t}=useCopy();
  return <>{error&&<ErrorNotice error={error}/>}<p className="ops-status" role="status" aria-live="polite">{pending?t('pending'):saved?t(successKey):''}</p></>;
}
