'use client';
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authenticatedRequest, useSession } from '@/features/identity/session';
import { BidiReference, Button, ButtonLink, Card, Checkbox, Input, LoadingRows, SectionState, StatusBadge, Textarea } from '@beirut-time/ui';
import { ApiError } from '@/lib/api/client';
import { normalizeDigits } from '@beirut-time/i18n';
import type { RepairQuotePage } from '@contracts/contracts-pricing/repair-quotes';
import type { AssessedQuote, Amounts, QuoteContext } from '@contracts/contracts-pricing/quotes/assessed';
import { repairMinor } from './input';
import { retainCommand } from './pending';
import { money } from '../pricing/money';
import { selectedAmounts } from '../pricing/assessed-amounts';
import { quoteDecision, stableOperation } from '../pricing/quote-commands';
import { QuoteDesk, QuoteGate, QuoteScope, QuoteFailure, SamplePolicy, useQuoteCopy, useQuoteScope, quoteBase, post, expiry } from '../pricing/s2-shared';

type Kind='repair';
type ReviewDraft={selected:string[];assessmentAccepted:boolean;returnAccepted:boolean;consent:boolean};
type PendingIssue={body:unknown;key:string;error?:unknown};
type PendingDecision={action:'accept'|'decline';body:ReturnType<typeof quoteDecision>;key:string;error?:unknown;resolved?:boolean};
const copy={en:{previous:'Previous',next:'Next',page:'Page',total:'Total quotes',support:'Contact support',expired:'Expired · return coordination unavailable',acknowledged:'Acknowledged fees only; collection is not confirmed',disclosed:'Disclosed assessment fee',disclosedReturn:'Disclosed return fee',handback:'Declining or expiry never authorizes repair or custody release. Return coordination remains unavailable until responsibility is confirmed. Only explicitly accepted assessment or return charges may be collected. Acceptance alone does not permit work: current custody, scope and confirmed platform-held simulated payment are required.'},ar:{previous:'السابق',next:'التالي',page:'الصفحة',total:'إجمالي عروض الأسعار',support:'التواصل مع الدعم',expired:'منتهي الصلاحية · تنسيق الإرجاع غير متاح',acknowledged:'الرسوم الموافق عليها فقط؛ التحصيل غير مؤكد',disclosed:'رسوم التقييم المعلنة',disclosedReturn:'رسوم الإرجاع المعلنة',handback:'الرفض أو انتهاء الصلاحية لا يسمح بالإصلاح أو تسليم العهدة. يبقى تنسيق الإرجاع غير متاح حتى تأكيد المسؤولية. لا تُحصّل رسوم التقييم أو الإرجاع إلا بموافقة صريحة عليها. الموافقة وحدها لا تسمح بالعمل: تلزم عهدة ونطاق حاليان ودفعة محاكاة مؤكدة محتجزة لدى المنصة.'}};
export function AmountReview({amounts,currency,policyRevision=2}:{amounts:Amounts;currency:'USD'|'LBP';policyRevision?:number}){
 const {locale,t}=useQuoteCopy();return <dl className="l14-fees">{([['parts_minor',t.parts],['labor_minor',t.labor],['assessment_fee_minor',t.assessment],['platform_fee_minor',policyRevision===2?t.businessFee:t.platformFee],['payable_minor',t.total],['seller_net_minor',policyRevision===2?t.businessNet:t.net]] as const).map(([field,label])=><div key={field} className={field==='payable_minor'?'l14-total':''}><dt>{label}</dt><dd><BidiReference>{money(amounts[field],currency,locale)}</BidiReference></dd></div>)}</dl>;
}
export function Review({quote,personal,suffix,onSaved,pending,drafts,draftId}:{quote:AssessedQuote;personal:boolean;suffix:string;onSaved:()=>void;pending:Map<string,PendingDecision>;drafts:Map<string,ReviewDraft>;draftId:string}){
 const retained=pending.get(quote.id);
 const {locale,t}=useQuoteCopy(),keys=useRef(new Map<string,string>());
 const [draft,setDraft]=useState(()=>retainCommand(drafts,draftId,()=>({
  selected:retained?.body.selected_line_ids??quote.decision?.selected_line_ids??quote.lines.filter(line=>line.mandatory).map(line=>line.id),
  assessmentAccepted:retained?.body.accept_assessment_fee??quote.decision?.accepted_fee_lines?.assessment??false,
  returnAccepted:retained?.body.accept_return_fee??quote.decision?.accepted_fee_lines?.return_transport??false,consent:false,
 })));
 const {assessmentAccepted,returnAccepted,consent}=draft;
 const selected=quote.decision?quote.decision.selected_line_ids:draft.selected;
 const updateDraft=(change:Partial<ReviewDraft>)=>{const next={...drafts.get(draftId)!,...change};drafts.set(draftId,next);setDraft(next);};
 const setConsent=(value:boolean)=>updateDraft({consent:value});
 const setSelected=(change:(current:string[])=>string[])=>updateDraft({selected:change(drafts.get(draftId)!.selected)});
 const setAssessmentAccepted=(value:boolean)=>updateDraft({assessmentAccepted:value});
 const setReturnAccepted=(value:boolean)=>updateDraft({returnAccepted:value});
 const uncertain=!!retained&&!retained.resolved;
 const [expired,setExpired]=useState(()=>Date.now()>=Date.parse(quote.expires_at));
 useEffect(()=>{const timer=setTimeout(()=>setExpired(true),Math.max(0,Date.parse(quote.expires_at)-Date.now()));return()=>clearTimeout(timer);},[quote.expires_at]);
 const totals=selectedAmounts(quote,selected),canDecide=personal&&quote.policy.revision===2&&quote.state==='issued'&&!expired;
 const save=useMutation({mutationFn:async(action:'accept'|'decline')=>{
  const body=quoteDecision(quote,action,selected,assessmentAccepted,returnAccepted);
  if(pending.get(quote.id)?.resolved)pending.delete(quote.id);
  const command=retainCommand(pending,quote.id,()=>({action,body,key:stableOperation(keys.current,[action,body])}));
  return authenticatedRequest(`${quoteBase}/${quote.kind}-quotes/${quote.id}/${command.action}${suffix}`,post(command.body,command.key));
 },onSuccess:()=>{pending.delete(quote.id);setConsent(false);onSaved();},onError:error=>{const unresolved=!(error instanceof ApiError&&error.status>=400&&error.status<500);const command=pending.get(quote.id);if(command){command.error=error;command.resolved=!unresolved;}onSaved();}});
 const text=copy[locale==='ar'?'ar':'en'];
 const canDecline=personal&&quote.policy.revision===2&&(quote.state==='issued'||quote.state==='expired_return_held');
 const status=expired&&quote.state==='issued'?'expired_return_held':quote.state;
 const declined=quote.decision?.state==='declined_return_held';
 return <Card className="l14-stack"><div className="l14-row"><h2>{quote.kind==='brand'?t.brandQuotes:t.repairQuotes} · {t.revision} {quote.revision}</h2><StatusBadge hue={status==='accepted'?'green':status==='issued'?'blue':'orange'}>{status==='expired_return_held'?text.expired:t[status]}</StatusBadge></div><p className="l14-terms">{quote.diagnosis}</p><ul className="l14-lines">{quote.lines.map(line=><li className="l14-line" key={line.id}><Checkbox checked={selected.includes(line.id)} disabled={!canDecide||line.mandatory||(save.isPending||uncertain)} onChange={event=>{setConsent(false);setSelected(current=>event.target.checked?[...current,line.id]:current.filter(id=>id!==line.id));}}>{line.label} · {line.mandatory?t.mandatory:t.optional}</Checkbox><div className="l14-row"><span>{line.kind==='part'?t.parts:t.labor}</span><BidiReference>{money(line.amount_minor,quote.currency,locale)}</BidiReference></div>{line.part_reference&&<BidiReference>{line.part_reference}</BidiReference>}</li>)}</ul><>{declined?<div><p>{text.acknowledged}</p><p>{t.assessment}: <BidiReference>{money(quote.decision?.accepted_fee_lines?.assessment?quote.assessment_fee_minor:0,quote.currency,locale)}</BidiReference></p><p>{t.returnFee}: <BidiReference>{money(quote.decision?.accepted_fee_lines?.return_transport?quote.return_fee_minor:0,quote.currency,locale)}</BidiReference></p><p>{text.disclosed}: <BidiReference>{money(quote.assessment_fee_minor,quote.currency,locale)}</BidiReference></p></div>:<AmountReview amounts={quote.decision?.amounts&&status==='accepted'?quote.decision.amounts:totals} currency={quote.currency} policyRevision={quote.policy.revision}/>}</><p>{text.disclosedReturn}: <BidiReference>{money(quote.return_fee_minor,quote.currency,locale)}</BidiReference></p><h3>{t.warranty}</h3><p className="l14-terms">{quote.warranty_terms}</p><h3>{t.modifications}</h3><p className="l14-terms">{quote.modification_terms}</p><p>{t.indicative}: <BidiReference>{money(quote.indicative_min_minor,quote.currency,locale)} – {money(quote.indicative_max_minor,quote.currency,locale)}</BidiReference></p><p className="l14-terms">{quote.indicative_basis}</p><p>{t.days}: {quote.lead_time_days}</p>{status==='accepted'?<p>{t.frozenEconomics}</p>:<p>{t.expires}: <BidiReference>{expiry(quote.expires_at,locale)}</BidiReference></p>}{quote.policy.revision===2?<p>{t.jobFeeTerms}</p>:<p>{t.legacyReadonly}</p>}<p className="l14-copy">{t.noExecution}</p><p>{text.handback}</p><ButtonLink variant="outline" href={`/${locale}/inbox`}>{text.support}</ButtonLink>{canDecide&&<>{quote.assessment_fee_minor>0&&<Checkbox disabled={(save.isPending||uncertain)} checked={assessmentAccepted} onChange={event=>{setAssessmentAccepted(event.target.checked);setConsent(false);}}>{t.acceptAssessmentFee}</Checkbox>}{quote.return_fee_minor>0&&<Checkbox disabled={(save.isPending||uncertain)} checked={returnAccepted} onChange={event=>{setReturnAccepted(event.target.checked);setConsent(false);}}>{t.acceptReturnFee}</Checkbox>}<Checkbox disabled={(save.isPending||uncertain)} checked={consent} onChange={event=>setConsent(event.target.checked)}>{t.termsConsent}</Checkbox><div className="l14-row"><Button disabled={!consent||!selected.length||(quote.assessment_fee_minor>0&&!assessmentAccepted)||(save.isPending||uncertain)} onClick={()=>save.mutate('accept')}>{(save.isPending||uncertain)?t.working:t.accept}</Button></div></>}{canDecline&&<Button variant="outline" disabled={(save.isPending||uncertain)} onClick={()=>save.mutate('decline')}>{t.decline}</Button>}<QuoteFailure error={save.error??retained?.error??(uncertain?true:null)} retry={uncertain?()=>{const command=pending.get(quote.id);if(command)save.mutate(command.action);}:onSaved}/></Card>;
}
export function Issue({kind,contextQuery,suffix,onSaved,commands,commandId}:{kind:Kind;contextQuery:string;suffix:string;onSaved:()=>void;commands:Map<string,PendingIssue>;commandId:string}){
 const retained=commands.get(commandId);
 const [uncertain,setUncertain]=useState(!!retained);
 const {t}=useQuoteCopy(),[fields,setFields]=useState<Record<string,string>>({assessment:'0',returnFee:'0',lead:'0',min:'0',max:'0',warranty:'',modifications:'',basis:''}),keys=useRef(new Map<string,string>());
 const context=useQuery({queryKey:['l14',kind,'context',contextQuery,suffix],queryFn:({signal})=>authenticatedRequest<QuoteContext>(`${quoteBase}/${kind}-quotes/context?${contextQuery}${suffix?'&'+suffix.slice(1):''}`,{signal})});
 const save=useMutation({mutationFn:async()=>{
  const original=commands.get(commandId);
  if(original)return authenticatedRequest(`${quoteBase}/${kind}-quotes${suffix}`,post(original.body,original.key));
  const c=context.data!;const lead=Number(normalizeDigits(fields.lead));
  if(!Number.isInteger(lead)||lead<0||lead>730)throw new Error('invalidFields');
  const body={source_id:c.source_id,source_revision:c.source_revision,assessment_id:c.assessment_id,assessment_revision:c.assessment_revision,currency:c.currency,lines:c.lines.map(line=>({...line,amount_minor:repairMinor(fields[line.id]??'')})),assessment_fee_minor:repairMinor(fields.assessment),return_fee_minor:repairMinor(fields.returnFee),warranty_terms:fields.warranty,modification_terms:fields.modifications,indicative_min_minor:repairMinor(fields.min),indicative_max_minor:repairMinor(fields.max),indicative_basis:fields.basis,lead_time_days:lead,schedule_id:'usd-job-v2'};
  // Locale changes preserve both the typed fields and the original operation.
  const command=retainCommand(commands,commandId,()=>({body,key:stableOperation(keys.current,body)}));
  return authenticatedRequest(`${quoteBase}/${kind}-quotes${suffix}`,post(command.body,command.key));
 },onSuccess:()=>{commands.delete(commandId);setUncertain(false);onSaved();},onError:error=>{const unresolved=!(error instanceof ApiError&&error.status>=400&&error.status<500)&&!(error instanceof Error&&['invalidFields','invalidMoney'].includes(error.message));const command=commands.get(commandId);if(!unresolved)commands.delete(commandId);else if(command)command.error=error;setUncertain(unresolved);}});
 const field=(id:string,label:string,area=false)=><label key={id}>{label}{area?<Textarea required maxLength={id==='basis'?1000:2000} value={fields[id]??''} onChange={event=>setFields(current=>({...current,[id]:event.target.value}))}/>:<Input required maxLength={20} inputMode="decimal" dir="ltr" value={fields[id]??''} onChange={event=>setFields(current=>({...current,[id]:event.target.value}))}/>}</label>;
 if(context.error instanceof ApiError&&[401,403].includes(context.error.status))return <QuoteFailure error={context.error} retry={()=>void context.refetch()}/>;
 return <Card className="l14-stack"><h2>{t.issue}</h2>{context.isPending?<LoadingRows label={t.loading}/>:context.data&&<form className="l14-form" onSubmit={event=>{event.preventDefault();save.mutate();}}><fieldset disabled={save.isPending||uncertain}><p className="l14-terms">{context.data.diagnosis}</p><p>{t.usdAmount} · {t.validFor}</p>{context.data.lines.map(line=>field(line.id,line.label))}<div className="l14-pair">{field('assessment',t.assessment)}{field('returnFee',t.returnFee)}{field('min',t.indicative+' · '+t.minimum)}{field('max',t.indicative+' · '+t.maximum)}{field('lead',t.days)}</div>{field('warranty',t.warranty,true)}{field('modifications',t.modifications,true)}{field('basis',t.indicative,true)}<Button type="submit" disabled={save.isPending}>{save.isPending?t.working:t.issue}</Button><Button type="button" variant="outline" disabled={!save.isSuccess||save.isPending} onClick={()=>{keys.current.clear();save.reset();}}>{t.freshPreview}</Button></fieldset></form>}{save.isSuccess&&<p role="status">{t.quoteSaved}</p>}<QuoteFailure error={context.error||save.error||retained?.error||(uncertain?true:null)} retry={uncertain?()=>save.mutate():()=>void context.refetch()}/></Card>;
}
function Workspace({kind,contextQuery}:{kind:Kind;contextQuery?:string}){
 const {scope,organization,setOrganization,suffix}=useQuoteScope(),{t,locale}=useQuoteCopy(),cache=useQueryClient(),[page,setPage]=useState(1);
 const [drafts]=useState(()=>new Map<string,ReviewDraft>());
 const [pending]=useState(()=>new Map<string,PendingDecision>());
 const [issues]=useState(()=>new Map<string,PendingIssue>());
 const [,setDecisionVersion]=useState(0);
 const text=copy[locale==='ar'?'ar':'en'];
 const rows=useQuery({queryKey:['l14',scope,kind,page],queryFn:({signal})=>authenticatedRequest<RepairQuotePage>(`${quoteBase}/${kind}-quotes${suffix}${suffix?'&':'?'}page=${page}`,{signal})});
 const refresh=()=>void cache.invalidateQueries({queryKey:['l14',scope,kind]});
 const decisionSaved=()=>{setDecisionVersion(value=>value+1);refresh();};
 if(rows.error instanceof ApiError&&[401,403].includes(rows.error.status))return <QuoteFailure error={rows.error} retry={refresh}/>;
 return <><QuoteScope value={organization} onChange={value=>{setOrganization(value);setPage(1);}}/><SamplePolicy/>{organization&&(contextQuery?<Issue key={`${scope}:${contextQuery}`} commands={issues} commandId={`${scope}:${contextQuery}`} kind={kind} contextQuery={contextQuery} suffix={suffix} onSaved={refresh}/>:<Card><SectionState title={t.assessmentContext} body={t.startAssessment}/></Card>)}<div className="l14-row"><Button variant="outline" onClick={refresh}>{t.refresh}</Button></div><QuoteFailure error={rows.error} retry={refresh}/>{rows.isPending?<Card><LoadingRows label={t.loading}/></Card>:rows.isError&&!rows.data?null:rows.data?.items.length===0?<Card><SectionState title={t.empty} body={t.emptyBody}/></Card>:<div className="l14-grid">{rows.data?.items.map(quote=><Review key={`${scope}:${quote.id}:${quote.revision}`} pending={pending} drafts={drafts} draftId={`${scope}:${quote.id}:${quote.revision}`} quote={quote} personal={!organization} suffix={suffix} onSaved={decisionSaved}/>)}</div>}{rows.data&&<nav aria-label={text.page} className="l14-row"><Button variant="outline" disabled={page<=1||rows.isFetching} onClick={()=>setPage(value=>value-1)}>{text.previous}</Button><span>{text.page} {page} · {text.total} {rows.data.total}</span><Button variant="outline" disabled={page*rows.data.page_size>=rows.data.total||rows.isFetching} onClick={()=>setPage(value=>value+1)}>{text.next}</Button></nav>}</>;
}
export default function RepairPage({contextQuery}:{contextQuery?:string}){const kind='repair';const session=useSession();return <QuoteDesk kind={`${kind}-quotes`}><QuoteGate next={`/${kind}-quotes${contextQuery?'?'+contextQuery:''}`}>{session&&<Workspace key={session.access_fingerprint} kind={kind} contextQuery={contextQuery}/>}</QuoteGate></QuoteDesk>;}
