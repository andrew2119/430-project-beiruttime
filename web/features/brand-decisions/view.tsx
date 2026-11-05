'use client';
import { useRef, useState } from 'react';
import { useQuery, useInfiniteQuery } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button, Card, State, Textarea, Select, StatusBadge, BidiReference, ButtonLink, AnimatedList } from '@beirut-time/ui';
import { PageHeader, PageLayout } from '@/shell/page-header';
import { useLocale } from '@/shell/locale-context';
import { useSession, authenticatedRequest, signInHref } from '@/features/identity/session';
import { useAccessContext } from '@/shell/access-context';
import { ApiError, request as publicRequest } from '@/lib/api/client';
import type { BrandRequest, Dimension } from '@contracts/contracts-catalog/request-drafts/v2';
import type { DecisionReadiness } from '@contracts/contracts-catalog/brand-decisions/v1';
import en from './en.json';
import ar from './ar.json';
import References from './references';
type Decision={id?:string;status:'not_decided'|'pending'|'approved'|'rejected'|'denied';request_revision:number;execution_authority:false;code?:string};
const root='/api/web/v1/catalog/v1';
const dimensions:Dimension[]=['color','material','dial','sophistication','movement'];
function path(value:string,organization:string){return root+value+(value.includes('?')?'&':'?')+'organization_id='+encodeURIComponent(organization);}
function label(value:unknown,locale:'en'|'ar'){if(typeof value==='string')return value;if(value&&typeof value==='object'&&locale in value&&typeof (value as Record<string,unknown>)[locale]==='string')return String((value as Record<string,unknown>)[locale]);return '—';}
export default function BrandDecisions(){
 const locale=useLocale(),t=locale==='ar'?ar:en,session=useSession(),access=useAccessContext(),router=useRouter(),params=useSearchParams();
 const org=params.get('organization_id')??session?.principal.actor.organization_id??'';
 const organizations=session?.principal.organizations??[];
 const businesses=useQuery({queryKey:['brand-workspace-labels',access.fingerprint],queryFn:()=>publicRequest<{items:{id:string;public_name:string}[]}>('/api/web/v1/identity/v1/businesses'),enabled:!!session,retry:false});
 const organizationLabel=(id:string)=>businesses.data?.items.find(item=>item.id===id)?.public_name??`\u2066${id}\u2069`;
 return <PageLayout><PageHeader title={t.title} count={t.intro} tools={<label className="bd-org">{t.organization}<Select aria-label={t.organization} value={org} options={[{value:'',label:t.chooseOrganization},...organizations.map(id=>({value:id,label:organizationLabel(id)}))]} onValueChange={id=>router.push(`/${locale}/business/customizations?organization_id=${encodeURIComponent(id)}`)}/></label>}/>
 {!session?<State title={t.title} body={t.signInBody}><ButtonLink href={signInHref('/business/customizations',locale)}>{t.signIn}</ButtonLink></State>:!org?<State title={t.chooseOrganization} body={t.intro}/>:<Board key={`${access.fingerprint}:${org}`} organization={org}/>}
 </PageLayout>;
}
function Board({organization}:{organization:string}){
 const locale=useLocale(),t=locale==='ar'?ar:en,access=useAccessContext();
 const query=useInfiniteQuery({queryKey:['brand-requests',access.fingerprint,organization],initialPageParam:null as string|null,queryFn:({signal,pageParam})=>authenticatedRequest<{items:BrandRequest[];next_cursor:string|null}>(path('/customization-requests'+(pageParam?'?before='+encodeURIComponent(pageParam):''),organization),{signal,accessFingerprint:access.fingerprint??undefined}),getNextPageParam:last=>last.next_cursor??undefined,retry:false});
 if(query.isPending)return <State kind="loading" title={t.title} body={t.loading}/>;
 if(!query.data)return <State kind="error" title={t.title} body={query.error instanceof ApiError&&query.error.status===403?t.denied:t.error}><Button onClick={()=>void query.refetch()}>{t.reload}</Button></State>;
 const byId=new Map<string,BrandRequest>();for(const item of query.data.pages.flatMap(page=>page.items)){if((byId.get(item.id)?.revision??0)<item.revision)byId.set(item.id,item);}
 const items=[...byId.values()];
 if(!items.length)return <State title={t.empty} body={t.intro}><Button onClick={()=>void query.refetch()}>{t.reload}</Button></State>;
 return <><AnimatedList className="bd-grid" role="list" aria-label={t.title} items={items} getKey={request=>request.id}>{request=><div role="listitem"><DecisionCard key={`${request.id}:${request.revision}`} request={request} organization={organization}/></div>}</AnimatedList>{query.error&&<p role="alert">{t.error}</p>}{query.hasNextPage&&<Button variant="outline" disabled={query.isFetchingNextPage} onClick={()=>void query.fetchNextPage()}>{t.moreRequests}</Button>}</>;
}
function DecisionCard({request,organization}:{request:BrandRequest;organization:string}){
 const locale=useLocale(),t=locale==='ar'?ar:en,access=useAccessContext();
 const[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState<unknown>(null);
 const operation=useRef<{key:string;body:Record<string,unknown>}|null>(null);
 const current=useQuery({queryKey:['brand-decision',access.fingerprint,organization,request.id,request.revision],queryFn:({signal})=>authenticatedRequest<Decision>(path(`/customization-requests/${request.id}/decision`,organization),{signal}),retry:false});
 const ready=useQuery({queryKey:['brand-decision-ready',access.fingerprint,organization,request.id,request.revision],queryFn:({signal})=>authenticatedRequest<DecisionReadiness>(path(`/customization-requests/${request.id}/decision-readiness`,organization),{signal}),retry:false});
 const readyBindings=!ready.error&&!ready.isFetching&&ready.data?.status==='available'?ready.data.bindings:null;
 const status=current.error?'unavailable':current.data?.status??(current.isPending?'loading':'unavailable'),frozen=!!current.error||current.isFetching||!current.data||status==='pending'||status==='approved'||status==='rejected';
 async function decide(decision:'approve'|'reject'){
  if(!readyBindings&&!operation.current)return;setBusy(true);setError(null);
  operation.current??={key:crypto.randomUUID(),body:{expected_revision:request.revision,decision,reason,...Object.fromEntries(Object.entries(readyBindings!).filter(([key])=>['assessment_id','assessment_revision','quote_id','quote_revision','grant_id','grant_revision'].includes(key)))}};
  setUncertain(true);
  try{const op=operation.current;await authenticatedRequest<Decision>(path(`/customization-requests/${request.id}/decisions`,organization),{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':op.key},body:JSON.stringify(op.body),accessFingerprint:access.fingerprint??undefined});operation.current=null;setUncertain(false);}
  catch(e){setError(e);if(e instanceof ApiError&&e.status<500){operation.current=null;setUncertain(false);}}
  finally{setBusy(false);void current.refetch();void ready.refetch();}
 }
 async function resume(){if(!current.data?.id)return;setBusy(true);setError(null);try{await authenticatedRequest(path(`/brand-decision-operations/${current.data.id}/resume`,organization),{method:'POST',accessFingerprint:access.fingerprint??undefined});operation.current=null;setUncertain(false);}catch(e){setError(e);}finally{setBusy(false);void current.refetch();}}
 if(current.error instanceof ApiError&&current.error.status===403)return <Card className="bd-card"><h2>{t.request}</h2><p role="alert">{t.denied}</p><Button variant="outline" onClick={()=>void current.refetch()}>{t.reload}</Button></Card>;
 return <Card className="bd-card"><h2>{t.request} <BidiReference>{request.id.slice(0,8)}</BidiReference> · {t.revision} {request.revision.toLocaleString(locale)}</h2>
 <StatusBadge hue={status==='approved'?'green':status==='pending'?'orange':'neutral'}>{status==='denied'?t.deniedStatus:status==='loading'?t.loading:status==='unavailable'?t.error:t[status]}</StatusBadge>
 <dl aria-label={t.scope}>{dimensions.map(dimension=><div key={dimension}><dt>{t[dimension]}</dt><dd>{label(request.configuration.selections[dimension].definition.label??request.configuration.selections[dimension].definition['label_'+locale],locale)} · <BidiReference>{request.configuration.selections[dimension].option_revision}</BidiReference></dd></div>)}</dl>
 <p>{request.scope_intent}</p><p>{request.notes}</p><References requestId={request.id} ids={request.configuration.reference_ids} organization={organization}/><section><h3>{t.readiness}</h3><p>{readyBindings?t.ready:ready.data?.status==='unavailable'?t.prerequisitesUnavailable:t.notReady}</p><p>{t.simulation}</p>{readyBindings&&<BidiReference>{new Intl.NumberFormat(locale,{style:'currency',currency:readyBindings.currency}).format(readyBindings.amount_minor/100)}</BidiReference>}</section>
 <label>{t.reason}<Textarea name="decision_reason" value={reason} maxLength={1000} disabled={busy||frozen||uncertain} onChange={event=>setReason(event.target.value)}/></label>
 <div className="bd-actions"><Button disabled={busy||frozen||uncertain||reason.trim().length<3||!readyBindings} onClick={()=>void decide('approve')}>{t.approve}</Button><Button variant="outline" disabled={busy||frozen||uncertain||reason.trim().length<3||!readyBindings} onClick={()=>void decide('reject')}>{t.reject}</Button>{uncertain&&status==='not_decided'&&<Button disabled={busy} onClick={()=>void decide(operation.current!.body.decision as 'approve'|'reject')}>{t.reconcile}</Button>}{status==='pending'&&<Button disabled={busy} onClick={()=>void resume()}>{t.reconcile}</Button>}<Button variant="outline" onClick={()=>{void current.refetch();void ready.refetch();}}>{t.reload}</Button></div>
 {(!!error||!!current.error)&&<p role="alert">{error instanceof ApiError&&error.status===403?t.denied:t.error}</p>}
 <RuleEditor request={request} organization={organization}/>
 </Card>;
}
function RuleEditor({request,organization}:{request:BrandRequest;organization:string}){
 const locale=useLocale(),t=locale==='ar'?ar:en,access=useAccessContext();
 const[status,setStatus]=useState('manual_assessment'),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState(false),[uncertain,setUncertain]=useState(false);
 type Rule={id:string;revision:number;option_ids:string[];base_model:string;caliber:string;mounting:Record<string,unknown>};
 const rules=useQuery({queryKey:['compatibility-rules',access.fingerprint,organization],queryFn:()=>authenticatedRequest<{items:Rule[]}>(path(`/brands/${organization}/compatibility`,organization)),retry:false});
 const ids=dimensions.map(d=>request.configuration.selections[d].option_id);
 const newRule=useRef(crypto.randomUUID()),pendingRule=useRef<{id:string;body:Record<string,unknown>}|null>(null);
 const old=rules.data?.items.find(rule=>rule.base_model===request.configuration.base_model&&rule.caliber===request.configuration.caliber&&JSON.stringify(rule.mounting)===JSON.stringify(request.configuration.movement_mounting)&&rule.option_ids.length===5&&ids.every(id=>rule.option_ids.includes(id)));
 async function publish(){
  pendingRule.current??={id:old?.id??newRule.current,body:{expected_revision:old?.revision??0,base_model:request.configuration.base_model,caliber:request.configuration.caliber,option_ids:ids,option_revisions:Object.fromEntries(dimensions.map(d=>[request.configuration.selections[d].option_id,request.configuration.selections[d].option_revision])),mounting:request.configuration.movement_mounting,status,reason}};
  setBusy(true);setError(false);setSaved(false);setUncertain(true);
  try{
   const command=pendingRule.current;
   await authenticatedRequest(path(`/brands/${organization}/compatibility/${command.id}`,organization),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(command.body),accessFingerprint:access.fingerprint??undefined});
   pendingRule.current=null;setUncertain(false);setSaved(true);void rules.refetch();
  }catch(e){setError(true);if(e instanceof ApiError&&e.status<500){pendingRule.current=null;setUncertain(false);}}
  finally{setBusy(false);}
 }
 return <section className="bd-card"><h3>{t.rule}</h3>
  <label>{t.ruleStatus}<Select aria-label={t.ruleStatus} disabled={busy||uncertain} value={status} onValueChange={value=>{setStatus(value);setSaved(false);}} options={(['valid','incompatible','parts_unavailable','manual_assessment'] as const).map(value=>({value,label:t[value]}))}/></label>
  <label>{t.ruleReason}<Textarea name="compatibility_reason" value={reason} disabled={busy||uncertain} maxLength={1000} onChange={e=>{setReason(e.target.value);setSaved(false);}}/></label>
  <div className="bd-actions"><Button variant="outline" disabled={busy||(!uncertain&&(!rules.data||reason.trim().length<3))} onClick={()=>void publish()}>{uncertain?t.ruleReconcile:t.saveRule}</Button><Button variant="outline" disabled={busy||rules.isFetching} onClick={()=>void rules.refetch()}>{t.reload}</Button></div>
  {rules.isPending&&<p role="status">{t.loading}</p>}{uncertain&&<p role="status">{t.rulePending}</p>}{saved&&<p role="status">{t.ruleSaved}</p>}{(error||!!rules.error)&&<p role="alert">{t.ruleError}</p>}
 </section>;
}
