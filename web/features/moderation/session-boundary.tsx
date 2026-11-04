'use client';
import { useEffect, useState } from 'react';
import { refreshSession, signInHref, useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import { ButtonLink, State } from '@beirut-time/ui';
import ModerationScreen from './moderation-screen';
import DashboardScreen from './dashboard-screen';
import IntakeScreen from './intake-screen';
import { ErrorNotice, FeatureFrame, LoadState, useCopy } from './common';

export default function OperationsBoundary({screen,initialCase,queueId}:{screen:'moderation'|'dashboard'|'intake';initialCase?:string;queueId?:string}) {
  const session=useSession();
  const {locale,t}=useCopy();
  const [state,setState]=useState<{loading:boolean;error?:unknown}>({loading:true});
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    if(session)return;
    let current=true;
    refreshSession().then(value=>{if(current)setState(value?{loading:false}:{loading:false,error:new ApiError(401,'unauthorized','')});},error=>{if(current)setState({loading:false,error});});
    return ()=>{current=false;};
  },[retry,session]);
  if(session) {
    const scope=session.access_fingerprint;
    if(screen==='moderation')return <ModerationScreen key={scope} token={scope} initialCase={initialCase}/>;
    if(screen==='intake')return <IntakeScreen key={scope} token={scope} organizations={session.principal.organizations}/>;
    return <DashboardScreen key={scope} token={scope} queueId={queueId}/>;
  }
  const next=screen==='intake'?'/business-intake':`/operations/${screen}`;
  const unauthorized=state.error instanceof ApiError&&state.error.status===401;
  return <FeatureFrame title={screen} intro={`${screen}Intro`}>{state.loading?<LoadState loading refresh={()=>{}}/>:unauthorized?<State title={t('signIn')} body={t('signInBody')}><ButtonLink href={signInHref(next,locale)}>{t('account')}</ButtonLink></State>:<ErrorNotice error={state.error} retry={()=>{setState({loading:true});setRetry(value=>value+1);}}/>}</FeatureFrame>;
}
