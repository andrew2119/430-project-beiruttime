'use client';

import { Component, useState, type ReactNode } from 'react';
import { ApiError } from '@/lib/api/client';
import { Button, ButtonLink, Card, Dialog, DialogContent, Input, RowSkeleton, Select, State, formatNumber } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { refreshSession, useSession, useSessionState } from '@/features/identity/session';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import type { AuditQuery, AuditReference, ResultState, Source } from '@contracts/contracts-comms/audit-references';
import { auditRead, operationRead } from './read';
import { copy } from './copy';
import { emptyFilters, queryFrom } from './filters';
import './styles.css';

type Copy = typeof copy.en | typeof copy.ar;
const sources:Source[] = ['trust','orders','service-operations'];
export default function AuditScreen() {
  const session = useSession(), state = useSessionState(), locale = useLocale(), t = copy[locale];
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>{session ? <AuditForm key={session.access_fingerprint} scope={session.access_fingerprint}
    organization={session.principal.actor.organization_id ?? ''} allowed={session.principal.roles.includes('operator') && session.principal.organization_grants.some(grant=>grant.organization_id===session.principal.actor.organization_id&&grant.permissions.includes('audit.references.read'))}/>
    : state==='restoring' ? <State kind="loading" title={t.loading} body={t.intro}><RowSkeleton/></State>
    : state==='unavailable' ? <State kind="error" title={t.unavailable} body={t.recovery}><Button onClick={()=>{void refreshSession().catch(()=>{});}}>{t.retry}</Button></State>
    : <State title={t.signIn} body={t.deniedBody}><ButtonLink href={`/${locale}/account`}>{t.account}</ButtonLink></State>}
  </PageBody></PageFrame>;
}

function AuditForm({scope,organization,allowed}:{scope:string;organization:string;allowed:boolean}) {
  const locale=useLocale(), t=copy[locale];
  const [filters,setFilters]=useState({...emptyFilters,organization});
  const [query,setQuery]=useState<AuditQuery|null>(null);
  const [invalid,setInvalid]=useState(false);
  const [generation,setGeneration]=useState(0);
  if (!allowed) return <State kind="error" title={t.denied} body={t.deniedBody}/>;
  const messages={placeholder:t.select,filter:t.filter,emptyTitle:t.noOptions,emptyBody:t.noOptionsBody,close:t.close,loading:t.loading,errorTitle:t.unavailable,errorBody:t.recovery,retry:t.retry};
  return <div className="audit-stack" data-page-answer><Card><form className="audit-filters" onSubmit={event=>{
    event.preventDefault();
    const next={...filters,operation:filters.operation||crypto.randomUUID()};
    setFilters(next);
    const value=queryFrom(next);setInvalid(!value);
    if(value){setQuery(value);setGeneration(value=>value+1);}
  }}>
    <Input label={t.organization} value={filters.organization} readOnly/>
    <Input label={t.actor} value={filters.actor} onValueChange={actor=>setFilters({...filters,actor})}/>
    <Input label={t.resource} value={filters.resource} onValueChange={resource=>setFilters({...filters,resource})}/>
    <Select label={t.outcome} messages={messages} value={filters.outcome} options={['','accepted','denied','pending','cancelled'].map(value=>({value,label:value?t[value as 'accepted'|'denied'|'pending'|'cancelled']:t.all}))} onValueChange={outcome=>setFilters({...filters,outcome})}/>
    <Input label={t.after} hint={t.dateHint} required value={filters.after} onValueChange={after=>setFilters({...filters,after})}/>
    <Input label={t.before} hint={t.dateHint} required value={filters.before} onValueChange={before=>setFilters({...filters,before})}/>
    <Input label={t.operation} value={filters.operation} onValueChange={operation=>setFilters({...filters,operation})}/>
    {invalid&&<State kind="error" title={t.invalid} body={t.dateHint}/>}
    <Button type="submit">{t.search}</Button>
  </form></Card>
  {query ? <AuditReadBoundary key={generation} t={t}><AnswerArrival view="audit-references"><div className="audit-stack">{sources.map(source=><SourcePanel key={`${source}:${generation}`} source={source} initial={query} scope={scope}/>)}</div></AnswerArrival></AuditReadBoundary>
    : <State title={t.initial} body={t.initialBody}/>}
  </div>;
}

export class AuditReadBoundary extends Component<{t:Copy;children:ReactNode},{unavailable:boolean}> {
  state={unavailable:false};
  static getDerivedStateFromError() { return {unavailable:true}; }
  render() {
    return this.state.unavailable ? <State kind="error" title={this.props.t.unavailable} body={this.props.t.readUnavailable}/> : this.props.children;
  }
}

function ReadFailure({error,retry}:{error:unknown;retry:()=>void}) {
  const locale=useLocale(), t=copy[locale];
  if(error instanceof ApiError&&error.status===401)return <State kind="error" title={t.signIn} body={t.deniedBody}><ButtonLink href={`/${locale}/account`}>{t.account}</ButtonLink></State>;
  return <Recovery state={error instanceof ApiError&&error.status===403?'denied':'unavailable'} t={t} retry={retry}/>;
}

function Recovery({state,t,retry}:{state:ResultState;t:Copy;retry:()=>void}) {
  return <State kind={state==='denied'||state==='stale'||state==='unavailable'?'error':state==='pending'?'loading':'empty'}
    title={t[state]} body={state==='denied'?t.deniedBody:state==='stale'?t.staleBody:t.recovery}>
    {state!=='stale'&&<Button onClick={retry}>{t.retry}</Button>}
  </State>;
}

export function SourcePanel({source,initial,scope}:{source:Source;initial:AuditQuery;scope:string}) {
  const locale=useLocale(), t=copy[locale];
  const [query,setQuery]=useState(initial);
  const [selected,setSelected]=useState<AuditReference|null>(null);
  const result=usePageRead(auditRead(scope,source,query));
  const part=!result.isError?result.data?.results.find(part=>part.source===source):undefined;
  const page=part?.page;
  const retry=()=>{void result.refetch();};
  const move=(offset:number)=>{if(page){setSelected(null);setQuery({...query,offset,expected_revision:page.revision});}};
  return <Card><section className="audit-stack" aria-label={t[source]}><h2>{t[source]}</h2>
    {result.isPending ? <State kind="loading" title={t.loading} body={t.intro}><RowSkeleton/></State>
      : result.isError||!part ? <ReadFailure error={result.error} retry={retry}/>
      : part.state!=='ready' ? <Recovery state={part.state} t={t} retry={retry}/>:null}
    {result.isFetching&&!result.isPending&&<p role="status">{t.loading}</p>}
    {page&&<><p>{t.total}: {formatNumber(page.total,locale)} · {t.revision}: {formatNumber(page.revision,locale)}</p>
      <ol className="audit-records">{page.items.map(item=><li key={item.operation_id}><Reference item={item} t={t}/>
        <Button variant="outline" onClick={()=>setSelected(item)}>{t.inspect}</Button></li>)}</ol>
      <div className="audit-actions"><Button variant="outline" disabled={query.offset===0||result.isFetching} onClick={()=>move(Math.max(0,query.offset-query.limit))}>{t.previous}</Button>
        <Button variant="outline" disabled={page.next_offset===null||result.isFetching} onClick={()=>{if(page.next_offset!==null)move(page.next_offset);}}>{t.next}</Button>
        <Button variant="outline" disabled={result.isFetching} onClick={retry}>{t.retry}</Button></div></>}
    <Dialog open={selected!==null&&!result.isError&&part?.state==='ready'} onOpenChange={open=>{if(!open)setSelected(null);}}>
      <DialogContent title={t.inspect} description={t.intro} closeLabel={t.close}>
        {selected&&!result.isError&&part?.state==='ready'&&<Operation scope={scope} source={source} item={selected}/>}</DialogContent>
    </Dialog>
  </section></Card>;
}

function Reference({item,t}:{item:AuditReference;t:Copy}) {
  const locale=useLocale();
  const date=(value:string)=>new Intl.DateTimeFormat(locale==='ar'?'ar-u-nu-arab':'en-u-nu-latn',{dateStyle:'medium',timeStyle:'long',timeZone:'Asia/Beirut'}).format(new Date(value));
  return <dl className="audit-reference">
    <dt>{t.operation}</dt><dd><bdi>{item.operation_id}</bdi></dd>
    <dt>{t.subject}</dt><dd><bdi>{item.subject_id}</bdi></dd>
    <dt>{t.actor}</dt><dd><bdi>{item.actor_id}</bdi></dd>
    <dt>{t.watch}</dt><dd><bdi>{item.watch_id??t.missing}</bdi></dd>
    <dt>{t.outcome}</dt><dd>{t[item.state]}</dd>
    <dt>{t.revision}</dt><dd>{formatNumber(item.expected_revision,locale)} → {formatNumber(item.revision,locale)}</dd>
    <dt>{t.occurred}</dt><dd><time dateTime={item.occurred_at}>{date(item.occurred_at)}</time></dd>
    <dt>{t.reason}</dt><dd>{t[item.reason_code]} · <bdi>{item.reason_reference}</bdi></dd>
    {item.state==='pending'&&<><dt>{t.nextActor}</dt><dd><bdi>{item.next_actor??t.missing}</bdi></dd><dt>{t.nextReview}</dt><dd>{item.next_review_at?<time dateTime={item.next_review_at}>{date(item.next_review_at)}</time>:t.missing}</dd></>}
  </dl>;
}

function Operation({scope,source,item}:{scope:string;source:Source;item:AuditReference}) {
  const t=copy[useLocale()];
  const result=usePageRead(operationRead(scope,source,item.organization_id,item.operation_id,item.revision));
  if(result.isPending)return <State kind="loading" title={t.loading} body={t.intro}/>;
  if(result.isError||!result.data)return <ReadFailure error={result.error} retry={()=>{void result.refetch();}}/>;
  if(result.data.state!=='ready'||!result.data.item)return <Recovery state={result.data.state==='ready'?'unavailable':result.data.state} t={t} retry={()=>{void result.refetch();}}/>;
  return <Reference item={result.data.item} t={t}/>;
}
