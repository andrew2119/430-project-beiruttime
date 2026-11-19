import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
const state=vi.hoisted(()=>({locale:'en',signedIn:true,mode:'success',total:1000,composed:true,moderate:true,assigned:['private'] as string[],seedPrivate:false,hookIndex:0,clears:[] as unknown[],seeded:[] as number[]}));
vi.mock('@/shell/foundation/path',()=>({usesFoundationShell:()=>state.composed}));
vi.mock('react',async importOriginal=>{
 const actual=await importOriginal<typeof import('react')>();
 return {...actual,useState:(initial:unknown)=>{
  const index=++state.hookIndex;
  const held={id:'private',question:'restricted evidence',answer:null,seller:'seller',revision:1,state:'held',reports:[{reason:'restricted report',created_at:''}],appeals:[]};
  const seed=state.seedPrivate&&(index===10||index===13);
  const [value,setValue]=actual.useState(seed?held:initial);
  if(seed)state.seeded.push(index);
  return [value,(next:unknown)=>{if(state.seedPrivate)state.clears.push([index,next]);setValue(next);}];
 }};

});
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/features/identity/session',()=>({useSession:()=>state.signedIn?{access_fingerprint:'current'}:null,authenticatedRequest:vi.fn(),signInHref:()=>'/login'}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({isPending:state.mode==='loading',isError:state.mode==='error',refetch:vi.fn(),data:state.mode==='success'?{items:Array.from({length:state.total===0?0:20},(_,i)=>({id:`question-${i}`,question:'الساعة ABC 😀 '.repeat(30),answer:i?'Yes نعم':null,seller:'seller',revision:1})),page:0,total:state.total,watch_id:'watch',source_revision:1,can_answer:true,can_moderate:state.moderate,assigned_question_ids:state.assigned}:undefined})}));
import ListingQuestionsPage, {Questions} from '../../../../web/features/listing-questions/view';
describe('Listing questions page',()=>{
 beforeEach(()=>{state.locale='en';state.signedIn=true;state.mode='success';state.total=1000;state.composed=true;state.moderate=true;state.assigned=['private'];state.seedPrivate=false;state.hookIndex=0;state.clears=[];state.seeded=[];});
 for(const locale of ['en','ar']) it(`renders canonical controls and server total in ${locale}`,()=>{
  state.locale=locale;
  const html=renderToStaticMarkup(<ListingQuestionsPage/>);
  expect(html).toContain('bt-page-header');
  expect(html).toContain(locale==='ar'?'أسئلة الإعلان':'Listing questions');
  expect(html).toContain('question-19');expect(html).not.toContain('question-20');
  expect(html).toContain(locale==='ar'?'١٬٠٠٠':'1,000');
  expect(html).toContain('dir="auto"');expect(html).not.toContain('<main');
 });
 it('renders empty and access recovery states',()=>{
  state.total=0;expect(renderToStaticMarkup(<ListingQuestionsPage/>)).toContain('No public questions');
  state.mode='error';expect(renderToStaticMarkup(<ListingQuestionsPage/>)).toContain('Questions unavailable');
  state.mode='success';state.total=1;state.signedIn=false;const html=renderToStaticMarkup(<ListingQuestionsPage/>);expect(html).toContain('Sign in to ask');expect(html).toContain('question-0');expect(html).not.toContain('Your public question');
 });
 it('retains private review while current permission allows it',()=>{
  state.seedPrivate=true;
  renderToStaticMarkup(<Questions listing="listing" onPending={()=>{}} signedIn/>);
  expect(state.seeded).toEqual([10,13]);expect(state.clears).toEqual([]);
 });
 it('clears retained private review when reassigned to another question',()=>{
  state.assigned=['another'];state.seedPrivate=true;
  const html=renderToStaticMarkup(<Questions listing="listing" onPending={()=>{}} signedIn/>);
  expect(html).not.toContain('restricted evidence');expect(html).not.toContain('restricted report');
  expect(state.clears).toEqual([[13,null],[10,null],[3,'']]);
 });
 it('clears retained private review when moderation is revoked',()=>{
  state.moderate=false;state.seedPrivate=true;
  const html=renderToStaticMarkup(<Questions listing="listing" onPending={()=>{}} signedIn/>);
  expect(html).not.toContain('restricted evidence');expect(html).not.toContain('restricted report');
  expect(state.seeded).toEqual([10,13]);
  expect(state.clears).toEqual([[13,null],[10,null],[3,'']]);
 });
});
