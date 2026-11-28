import { beforeEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AssessedQuote, QuoteContext } from '../../../../packages/contracts-pricing/quotes/assessed';

const state=vi.hoisted(()=>({locale:'en',context:{} as QuoteContext,mutations:[] as {mutationFn:(...args:never[])=>Promise<unknown>;onError:(error:unknown)=>void;onSuccess:()=>void}[]}));
vi.mock('@tanstack/react-query',()=>({
 useQuery:()=>({data:state.context,isPending:false}),
 useMutation:(options:typeof state.mutations[number])=>{state.mutations.push(options);return {isPending:false,isSuccess:false,error:null,mutate:()=>{},reset:()=>{}};},
 useQueryClient:()=>({}),
}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:vi.fn(),useSession:()=>null}));
vi.mock('@/features/pricing/s2-shared',async()=>{
 const en=(await import('../../../../web/features/pricing/s2-en.json')).default;
 const ar=(await import('../../../../web/features/pricing/s2-ar.json')).default;
 return {useQuoteCopy:()=>({locale:state.locale,t:state.locale==='ar'?ar:en}),quoteBase:'/quotes',
 post:(body:unknown,key:string)=>({body:JSON.stringify(body),headers:{'Idempotency-Key':key}}),expiry:()=>'',
 QuoteFailure:({error}:{error:unknown})=>error?<p>Recovery</p>:null,
 QuoteDesk:()=>null,QuoteGate:()=>null,QuoteScope:()=>null,SamplePolicy:()=>null,useQuoteScope:()=>({})};
});
vi.mock('@beirut-time/ui',()=>({
 BidiReference:({children}:{children:React.ReactNode})=><span>{children}</span>,
 Button:({children,disabled}:{children:React.ReactNode;disabled?:boolean})=><button disabled={disabled}>{children}</button>,
 ButtonLink:()=>null,Card:({children}:{children:React.ReactNode})=><section>{children}</section>,
 Checkbox:({children,checked,disabled}:{children:React.ReactNode;checked:boolean;disabled:boolean})=><label><input type="checkbox" checked={checked} disabled={disabled} readOnly/>{children}</label>,
 Input:()=>null,Textarea:()=>null,LoadingRows:()=>null,SectionState:()=>null,
 StatusBadge:({children}:{children:React.ReactNode})=><span>{children}</span>,
}));
import { Issue, Review } from '../../../../web/features/repair-quotes/repair-page';
import { authenticatedRequest } from '../../../../web/features/identity/session';

type Creation={body:unknown;key:string;error?:unknown};
const context:QuoteContext={source_id:'case',source_revision:1,assessment_id:'assessment',assessment_revision:1,currency:'USD',diagnosis:'Seal',lines:[]};
beforeEach(()=>{state.locale='en';state.context=context;state.mutations=[];vi.mocked(authenticatedRequest).mockReset();});

it('recovers creation after a lost response and business remount before creating anything else',async()=>{
 const commands=new Map<string,Creation>();
 const original={body:{...context,assessment_fee_minor:100,return_fee_minor:200},key:'repair-issue-once',error:new Error('timeout')};
 commands.set('business-one:case',original);
 const mount=(scope:string)=>renderToStaticMarkup(<Issue kind="repair" contextQuery="case" suffix={`?organization_id=${scope}`} commands={commands} commandId={`${scope}:case`} onSaved={()=>{}}/>);
 mount('business-two');
 state.locale='ar';
 const recovered=mount('business-one');
 expect(recovered).toContain('fieldset disabled');
 expect(recovered).toContain('Recovery');
 const mutation=state.mutations.at(-1)!;
 vi.mocked(authenticatedRequest).mockRejectedValueOnce(new Error('timeout'));
 await expect(mutation.mutationFn()).rejects.toThrow('timeout');
 mutation.onError(new Error('timeout'));
 expect(commands.get('business-one:case')).toBe(original);
 const request=vi.mocked(authenticatedRequest).mock.calls[0];
 expect(request[0]).toBe('/quotes/repair-quotes?organization_id=business-one');
 expect(request[1]?.body).toBe(JSON.stringify(original.body));
 expect(request[1]?.headers).toEqual({'Idempotency-Key':'repair-issue-once'});
 mount('business-two');mount('business-one');
 vi.mocked(authenticatedRequest).mockResolvedValueOnce({status:'succeeded'});
 await state.mutations.at(-1)!.mutationFn();
 state.mutations.at(-1)!.onSuccess();
 expect(commands.has('business-one:case')).toBe(false);
});

it('offers recovery when remounting an in-flight creation before its response',()=>{
 const commands=new Map<string,Creation>([['business:case',{body:context,key:'in-flight'}]]);
 const html=renderToStaticMarkup(<Issue kind="repair" contextQuery="case" suffix="?organization_id=business" commands={commands} commandId="business:case" onSaved={()=>{}}/>);
 expect(html).toContain('fieldset disabled');expect(html).toContain('Recovery');
});

it.each(['en','ar'])('renders retained decisions, declined fees and in-flight recovery in %s',async locale=>{
 state.locale=locale;
 const amounts={parts_minor:300,labor_minor:0,assessment_fee_minor:0,platform_fee_minor:15,seller_commission_minor:15,seller_net_minor:285,payable_minor:300};
 const quote:AssessedQuote={id:'quote',revision:1,kind:'repair',source_id:'case',source_revision:1,assessment_id:'assessment',assessment_revision:1,buyer_id:'buyer',organization_id:'business',author_id:'author',diagnosis:'Seal',currency:'USD',
 lines:[{id:'mandatory',label:'Required',kind:'part',mandatory:true,amount_minor:100,part_reference:null},{id:'old',label:'Old choice',kind:'part',mandatory:false,amount_minor:900,part_reference:null},{id:'new',label:'Accepted choice',kind:'part',mandatory:false,amount_minor:200,part_reference:null}],
 assessment_fee_minor:0,return_fee_minor:0,warranty_terms:'Terms',modification_terms:'None',indicative_min_minor:100,indicative_max_minor:1000,indicative_basis:'Parts',lead_time_days:1,expires_at:'2030-01-01T00:00:00Z',economics_expires_at:null,terms_digest:'digest',policy:{sample:true,schedule_id:'usd-job-v2',revision:2,buyer_fee_bps:0,business_fee_bps:500,seller_commission_bps:500,rounding:'half_up',minor_unit_exponent:2},full_total:amounts,state:'issued',decision:null};
 const draft={selected:['mandatory','old'],assessmentAccepted:false,returnAccepted:false,consent:false};
 const drafts=new Map([['draft',draft]]);
 const render=()=>renderToStaticMarkup(<Review quote={quote} personal suffix="" onSaved={()=>{}} pending={new Map()} drafts={drafts} draftId="draft"/>);
 const before=render();
 expect(before).toMatch(/checked=""[^>]*\/>Old choice/);
 quote.state='accepted';quote.decision={state:'accepted',actor_id:'buyer',accepted_at:'2026-11-16T00:00:00Z',selected_line_ids:['mandatory','new'],amounts,terms_digest:'digest',accepted_fee_lines:{}};
 const after=render();
 expect(after).toMatch(/checked=""[^>]*\/>Accepted choice/);
 expect(after).not.toMatch(/checked=""[^>]*\/>Old choice/);
 expect(after).toContain(locale==='ar'?'٣٫٠٠':'3.00');
 expect(draft.selected).toEqual(['mandatory','old']);
 quote.state='declined_return_held';
 quote.assessment_fee_minor=1250;quote.return_fee_minor=750;
 quote.decision={...quote.decision,state:'declined_return_held',selected_line_ids:[],accepted_fee_lines:{assessment:false,return_transport:false}};
 const declined=render();
 expect(declined).not.toContain('l14-total');
 expect(declined).toContain(locale==='ar'?'الرسوم الموافق عليها فقط':'Acknowledged fees only');
 expect(declined).toContain(locale==='ar'?'٠٫٠٠':'0.00');
 quote.state='issued';quote.decision=null;
 const pending:Parameters<typeof Review>[0]['pending']=new Map([['quote',{action:'accept',body:{quote_revision:1,selected_line_ids:['mandatory','new'],payable_minor:300,terms_digest:'digest',accept_assessment_fee:false,accept_return_fee:false},key:'decision-in-flight'}]]);
 const remount=()=>renderToStaticMarkup(<Review quote={quote} personal suffix="" onSaved={()=>{}} pending={pending} drafts={drafts} draftId="draft"/>);
 remount();
 const returned=remount();
 expect(returned).toContain('Recovery');
 expect(pending.get('quote')?.key).toBe('decision-in-flight');
 vi.mocked(authenticatedRequest).mockResolvedValueOnce({status:'succeeded'});
 await state.mutations.at(-1)!.mutationFn('decline' as never);
 const retry=vi.mocked(authenticatedRequest).mock.calls.at(-1)!;
 expect(retry[0]).toBe('/quotes/repair-quotes/quote/accept');
 expect(retry[1]?.headers).toEqual({'Idempotency-Key':'decision-in-flight'});
 expect(retry[1]?.body).toBe(JSON.stringify(pending.get('quote')!.body));
 state.mutations.at(-1)!.onSuccess();
 expect(pending.has('quote')).toBe(false);
});
