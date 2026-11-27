'use client';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Button, ButtonLink, Card, Dialog, DialogContent, Select, State, formatAmount } from '@beirut-time/ui/foundation';
import { PageFrame as PageLayout, PageHeader, PageBody, PageLoading } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { useAccessContext } from '@/shell/access-context';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { usePageRead } from '@/lib/page-speed/read';
import { useSession } from '@/features/identity/session';
import { ApiError } from '@/lib/api/client';
import type { Command, Decision, Detail } from '@contracts/contracts-service/finish';
import { copy } from './copy';
import './styles.css';
import { finishRead, record, lookup } from './api';
import { centsToDollars, makeCommand, permitsIntervention, recoverOrRecord } from './model';

export default function Finish() {
  useSession();
  const access=useAccessContext();
  return <Content key={access.fingerprint??'private'} fingerprint={access.fingerprint}/>;
}
function Content({fingerprint}:{fingerprint:string|null}) {
  const locale=useLocale(),t=copy[locale],params=useSearchParams();
  const subject=params.get('subject')??'';
  const [reviewRevision,setReviewRevision]=useState(0);
  const [commandDenied,setCommandDenied]=useState(false);
  const valid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(subject);
  const read=usePageRead(fingerprint&&valid&&!commandDenied?finishRead(subject,fingerprint):null);
  const denied=commandDenied||(read.error instanceof ApiError && [401,403,404].includes(read.error.status));
  return <PageLayout><PageHeader title={t.title} lead={t.intro}/><PageBody>
    {!fingerprint?<State kind="error" title={t.title} body={t.denied}/>:!valid?<State title={t.title} body={t.empty}/>:!denied&&read.data?
      <AnswerArrival view="finish.v1"><ConsentForm key={`${subject}:${reviewRevision}`} detail={read.data} fingerprint={fingerprint} deny={()=>setCommandDenied(true)} refresh={()=>{void read.refetch().then(result=>{if(result.isSuccess)setReviewRevision(value=>value+1);});}}/></AnswerArrival>:
      denied?<State kind="error" title={t.title} body={t.denied}/>:read.isPending?<PageLoading label={t.loading}/>:<State kind="error" title={t.title} body={denied?t.denied:t.unavailable}><Button onClick={()=>void read.refetch()}>{t.retry}</Button></State>}

  </PageBody></PageLayout>;
}
function ConsentForm({detail:initialDetail,fingerprint,refresh,deny}:{detail:Detail;fingerprint:string;refresh:()=>void;deny:()=>void}) {
  const locale=useLocale(),t=copy[locale];
  const [detail]=useState(initialDetail);
  const [choices,setChoices]=useState<Record<string,Decision>>(()=>Object.fromEntries(detail.choices.map(c=>[c.area_id,c.decision])));
  const [attempt,setAttempt]=useState<Command|null>(null);
  const [state,setState]=useState<'editing'|'sending'|'pending'|'recorded'|'stale'|'denied'|'error'>(detail.choices.length?'recorded':'editing');
  const [review,setReview]=useState(false);
  const active=useRef<AbortController|null>(null);
  const busy=useRef(false);
  useEffect(()=>()=>{active.current?.abort();},[]);
  const locked=attempt!==null;
  const complete=detail.source.areas.every(a=>Boolean(choices[a.area_id]));
  async function submit() {
    if(busy.current) return;
    const command=attempt??makeCommand(detail,choices,crypto.randomUUID());
    setAttempt(command);setReview(false);setState('sending');busy.current=true;
    const controller=new AbortController();active.current=controller;
    try {
      const result=attempt
        ?await recoverOrRecord(()=>lookup(command,fingerprint,controller.signal),()=>record(command,fingerprint,controller.signal),error=>error instanceof ApiError&&error.status===404)
        :await record(command,fingerprint,controller.signal);
      if(!controller.signal.aborted) setState(result.state);
    } catch(error) {
      if(controller.signal.aborted) return;
      if(error instanceof ApiError && [401,403,404].includes(error.status)) deny();
      else if(error instanceof ApiError && error.status===409) {
        try {
          const recovered=await lookup(command,fingerprint,controller.signal);
          if(!controller.signal.aborted) setState(recovered.state);
        } catch(recovery) {
          if(controller.signal.aborted) return;
          if(recovery instanceof ApiError && recovery.status===404) setState('stale');
          else if(recovery instanceof ApiError && [401,403].includes(recovery.status)) deny();
          else setState('pending');
        }
      }
      else setState('pending');
    } finally {busy.current=false;}
  }
  const messages={placeholder:t.select,filter:t.filter,emptyTitle:t.noOptions,emptyBody:t.noOptionsBody,close:t.close,loading:t.loading,errorTitle:t.optionsError,errorBody:t.unavailable,retry:t.retry};
  return <form className="finish-scope" onSubmit={e=>{e.preventDefault();if(complete&&!locked)setReview(true);}}>
    <p>{t.amount}: <bdi>{formatAmount(centsToDollars(detail.source.total_minor),locale,locale==='ar'?'دولار أمريكي':'USD','—')}</bdi></p>
    <Card>
      <h2>{t.terms}</h2>
      <p dir="auto">{locale==='ar'?detail.source.terms.fee_ar:detail.source.terms.fee_en}</p>
      <p dir="auto">{locale==='ar'?detail.source.terms.return_ar:detail.source.terms.return_en}</p>
      <p dir="auto">{locale==='ar'?detail.source.terms.assurance_ar:detail.source.terms.assurance_en}</p>
      <ButtonLink href={`/${locale}${detail.source.terms.support_path}`}>{t.support}</ButtonLink>
    </Card>
    {detail.source.areas.map(area=><Card key={area.area_id}>
      <h2 dir="auto">{locale==='ar'?area.name_ar:area.name_en}</h2>
      <dl>
        <dt>{t.original}</dt><dd>{t[area.original]}</dd><dt>{t.desired}</dt><dd>{t[area.desired]}</dd>
        <dt>{t.material}</dt><dd dir="auto">{!area.material_known?t.unknown:locale==='ar'?area.material_ar:area.material_en}</dd>
        <dt>{t.coating}</dt><dd>{t[area.coating]}</dd><dt>{t.plating}</dt><dd>{t[area.plating]}</dd><dt>{t.engraving}</dt><dd>{t[area.engraving]}</dd>
        <dt>{t.action}</dt><dd>{t[area.assessed_action]}</dd><dt>{t.limits}</dt><dd dir="auto">{!area.preservation_assessed?t.unknown:locale==='ar'?area.preservation_ar:area.preservation_en}</dd>
      </dl>
      {!permitsIntervention(area)&&<p>{t.restricted}</p>}
      <Select label={t.choice} value={choices[area.area_id]??null} disabled={locked} messages={messages}
        options={[{value:'no_polish',label:t.no_polish},{value:'consent',label:t.consent,disabled:!permitsIntervention(area)}]}
        onValueChange={value=>{setChoices(old=>({...old,[area.area_id]:value as Decision}));setState('editing');}}/>
    </Card>)}
    {attempt&&<p>{t.reference}: <bdi>{attempt.operation_id}</bdi></p>}
    {state!=='editing'&&<State kind={state==='denied'||state==='stale'||state==='error'?'error':state==='sending'?'loading':'empty'} title={t.title} body={state==='sending'?t.loading:t[state]}/>}
    {!locked&&<Button type="submit" disabled={!complete}>{t.review}</Button>}
    {state==='pending'&&<Button type="button" onClick={()=>void submit()}>{t.retry}</Button>}
    {(state==='stale'||state==='recorded')&&<Button type="button" onClick={refresh}>{t.refresh}</Button>}
    <Dialog open={review} onOpenChange={setReview}><DialogContent title={t.confirm} closeLabel={t.close} description={t.reviewBody}>
      <Button type="button" onClick={()=>void submit()}>{t.save}</Button><Button type="button" variant="outline" onClick={()=>setReview(false)}>{t.cancel}</Button>
    </DialogContent></Dialog>
  </form>;
}
