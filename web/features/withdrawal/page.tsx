'use client';
import {useRef,useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {Archive} from 'lucide-react';
import {AnimatedList,BidiReference,Button,ButtonLink,Card,CardHead,Dialog,DialogContent,DialogDescription,DialogTitle,Input,Label,LoadingRows,Notice,SectionState,Select,StatusBadge} from '@beirut-time/ui';
import {PageHeader,PageLayout} from '@/shell/page-header';
import {useLocale} from '@/shell/locale-context';
import {authenticatedRequest,useSession,useSessionState,signInHref} from '@/features/identity/session';
import {ApiError} from '@/lib/api/client';
import en from './en.json';
import ar from './ar.json';

type Listing={id:string;revision:number;status:string;is_demo:boolean;facts:{brand:string;model:string}};
type Intent={id:string;listing_id:string;base_revision:number;state:'pending'|'denied'|'succeeded';operation_key:string;reason:string;status:string;next_action?:string;outcome?:{exception_route?:string|null}};
const catalog='/api/web/v1/catalog/v1';
export default function Withdrawals(){
  const locale=useLocale(),t=locale==='ar'?ar:en,session=useSession(),state=useSessionState();
  return <PageLayout className="withdrawal-page"><PageHeader title={t.title} count={t.intro}/>{session?<Workspace key={session.access_fingerprint}/>:<Card>{state==='restoring'?<LoadingRows label={t.loading}/>:<SectionState title={state==='unavailable'?t.unavailable:t.signIn} kind="locked"><ButtonLink href={signInHref('/seller/withdrawals',locale)}>{t.signIn}</ButtonLink></SectionState>}</Card>}</PageLayout>;
}
function Workspace(){
  const locale=useLocale(),t=locale==='ar'?ar:en,session=useSession()!;
  const[organization,setOrganization]=useState(''),[selected,setSelected]=useState<Listing|null>(null),[reason,setReason]=useState(''),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  const[operation,setOperation]=useState<{key:string;listing:Listing;reason:string}|null>(null);
  const inflight=useRef(false);
  const [historyPage,setHistoryPage]=useState(1);
  const pageSize=25;
  const client=useQueryClient();
  const query=organization?'?organization_id='+encodeURIComponent(organization):'';
  const listings=useQuery({queryKey:['l13-withdraw-stock',session.access_fingerprint,organization],queryFn:({signal})=>authenticatedRequest<{items:Listing[]}>(catalog+'/seller/listings'+query,{signal}),retry:false});
  const history=useQuery({queryKey:['l13-withdrawals',session.access_fingerprint,organization,historyPage],queryFn:({signal})=>authenticatedRequest<{items:Intent[];total:number;page:number;page_size:number}>(catalog+'/me/withdrawals'+query+(query?'&':'?')+`page=${historyPage}&page_size=${pageSize}`,{signal}),retry:false,refetchInterval:15000,placeholderData:(previous,previousQuery)=>previousQuery?.queryKey[1]===session.access_fingerprint&&previousQuery.queryKey[2]===organization&&!!client.getQueryCache().get(previousQuery.queryHash)?previous:undefined});
  async function send(listing:Listing,text:string,key:string){
    if(inflight.current)return;inflight.current=true;setBusy(true);setError(null);setOperation({listing,reason:text,key});
    try{
      const value=await authenticatedRequest<Intent>(`${catalog}/listings/${listing.id}/withdrawals${query}`,{method:'POST',accessFingerprint:session.access_fingerprint,headers:{'Content-Type':'application/json','Idempotency-Key':key,'If-Match':String(listing.revision)},body:JSON.stringify({reason:text})});
      if(!['pending','denied','succeeded'].includes(value.status))throw new ApiError(503,'withdrawal_unknown','');
      setOperation(null);setSelected(null);void listings.refetch();void history.refetch();
      if(value.status==='denied')setError(new ApiError(409,'commitment_exists',''));
    }catch(e){setError(e);if(e instanceof ApiError&&e.status<500)setOperation(null);void history.refetch();}finally{inflight.current=false;setBusy(false);}
  }
  const grants=session.principal.organization_grants??[];
  return <><Card className="withdrawal-stack"><Label htmlFor="withdrawal-scope">{t.scope}</Label><Select id="withdrawal-scope" aria-label={t.scope} value={organization||'personal'} disabled={busy||!!operation} onValueChange={value=>{setOrganization(value==='personal'?'':value);setHistoryPage(1);setSelected(null);}} options={[{value:'personal',label:t.personal},...grants.filter(g=>g.permissions.includes('business.stock.write')).map(g=>({value:g.organization_id,label:g.organization_id}))]}/></Card>
    {!!error&&<Card><SectionState title={error instanceof ApiError&&error.status<500?t.denied:t.unavailable} kind="error">{operation&&<Button disabled={busy} onClick={()=>void send(operation.listing,operation.reason,operation.key)}>{t.retry}</Button>}</SectionState></Card>}
    <Card><CardHead title={t.published} icon={Archive}/>{listings.isPending?<LoadingRows label={t.loading}/>:listings.error?<SectionState title={listings.error instanceof ApiError&&listings.error.status<500?t.denied:t.unavailable} kind="error"><Button onClick={()=>void listings.refetch()}>{t.reload}</Button></SectionState>:!listings.data?.items.some(l=>l.status==='published')?<SectionState title={t.empty} icon={Archive}/>:<AnimatedList className="withdrawal-stack" items={listings.data.items.filter(l=>l.status==='published')} getKey={listing=>listing.id}>{listing=><article className="withdrawal-row"><div><h2>{listing.facts.brand} {listing.facts.model}</h2>{listing.is_demo&&<p>{t.sample}</p>}<BidiReference>{listing.id}</BidiReference></div><Button variant="outline" disabled={busy||!!operation} onClick={()=>{setReason('');setSelected(listing);}}>{t.withdraw}</Button></article>}</AnimatedList>}</Card>
    <Card><CardHead title={t.history} icon={Archive}/>{history.isFetching&&history.data&&<p role="status">{history.isPlaceholderData?t.loadingHistoryPage:t.refreshingHistory}</p>}{history.isPending?<LoadingRows label={t.loading}/>:history.error?<SectionState title={history.error instanceof ApiError&&history.error.status<500?t.denied:t.unavailable} kind="error"><Button onClick={()=>void history.refetch()}>{t.reload}</Button></SectionState>:history.data?.items.length?<AnimatedList className="withdrawal-stack" items={history.data.items} getKey={intent=>intent.id}>{intent=><article className="withdrawal-row"><div><StatusBadge hue={intent.state==='succeeded'?'green':intent.state==='denied'?'pink':'orange'}>{intent.next_action==='reload'?t.stale:t[intent.state]}</StatusBadge><p><BidiReference>{intent.listing_id}</BidiReference></p></div>{intent.state==='pending'?<Button disabled={busy} onClick={()=>void send({id:intent.listing_id,revision:intent.base_revision,status:'withdrawal_pending',is_demo:false,facts:{brand:'',model:''}},intent.reason,intent.operation_key)}>{t.retry}</Button>:intent.next_action==='reload'?<Button disabled={busy} onClick={()=>{void listings.refetch();void history.refetch();}}>{t.reload}</Button>:intent.state==='denied'?<ButtonLink href={`/${locale}${intent.outcome?.exception_route??'/checkout'}`} variant="outline">{t.exception}</ButtonLink>:null}</article>}</AnimatedList>:<SectionState title={t.none} icon={Archive}/>}</Card>
    <Card><nav aria-label={t.historyPages} className="withdrawal-row"><Button variant="outline" disabled={busy||history.isPlaceholderData||historyPage===1} onClick={()=>setHistoryPage(page=>page-1)}>{t.previous}</Button><p aria-live="polite">{t.page} {history.data?.page??historyPage} · {t.total} {history.data?.total??'—'}</p><Button variant="outline" disabled={busy||history.isPlaceholderData||!history.data||historyPage*pageSize>=history.data.total} onClick={()=>setHistoryPage(page=>page+1)}>{t.next}</Button></nav></Card>
    <Dialog open={!!selected} onOpenChange={open=>{if(!open&&!busy&&!operation)setSelected(null);}}><DialogContent closeLabel={t.close}><DialogTitle>{t.withdraw}</DialogTitle><DialogDescription>{t.warning}</DialogDescription><Notice>{selected?.facts.brand} {selected?.facts.model}</Notice><form className="withdrawal-stack" onSubmit={event=>{event.preventDefault();if(selected)void send(selected,reason,operation?.key??crypto.randomUUID());}}><Label htmlFor="withdrawal-reason">{t.reason}</Label><Input id="withdrawal-reason" required maxLength={200} value={reason} onChange={e=>setReason(e.target.value)} disabled={busy||!!operation}/><Button type="submit" variant="destructive" disabled={busy||!reason.trim()}>{busy?t.loading:operation?t.retry:t.confirm}</Button><Button type="button" variant="ghost" disabled={busy||!!operation} onClick={()=>setSelected(null)}>{t.cancel}</Button></form></DialogContent></Dialog>
  </>;
}
