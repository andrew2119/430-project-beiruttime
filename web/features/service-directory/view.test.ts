import { beforeEach, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import en from './en.json';
import ar from './ar.json';
import { usdCents } from '../movement-option/offering';
import { formatMinor } from '../movement-option/money';
import { DirectoryAvailability } from './availability';
import movementEn from '../movement-option/en.json';
import requestEn from '../request-drafts/en.json';
import requestAr from '../request-drafts/ar.json';
const state = vi.hoisted(() => ({ locale: 'en' as 'en' | 'ar', pending: false, error: false, commandPending:false, pinned:false, listOnly:false, privateError:null as unknown }));
const brand = '00000000-0011-4000-8000-000000000001';
vi.mock('next/link', () => ({ default: 'a' }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }), useSearchParams: () => new URLSearchParams('business='+brand) }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => state.locale }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: 'synthetic', roles: ['buyer'] }) }));
vi.mock('@/features/identity/session', () => ({ useSession: () => ({ access_fingerprint: 'synthetic', principal: { roles: ['buyer'] } }), signInHref: () => '/en/account', authenticatedRequest: vi.fn(), refreshSession: vi.fn() }));
vi.mock('@/lib/page-speed/arrival',()=>({AnswerArrival:({children}:{children:React.ReactNode})=>children}));
vi.mock('./api',async importOriginal=>({...await importOriginal<typeof import('./api')>(),useCommandMutation:()=>({isPending:state.commandPending,isError:false,isSuccess:false,needsRecovery:false,mutate:vi.fn(),reset:vi.fn()})}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:(read:{key:unknown[]}|null)=>{
  const key=read?.key[0];
  const business={ organization_id: brand, revision: 1, display_name: 'Synthetic official brand · ساعة ⌚', kind: 'brand', sample: true, capabilities: ['maintenance', 'customization'], contact: 'sample@example.invalid', visit_en: 'By arrangement', visit_ar: 'بموعد مسبق', scope_en: 'Indicative scope', scope_ar: 'نطاق إرشادي' };
  const movement={ id: 'movement', brand_id: brand, revision: 1, label_en: 'Synthetic movement', label_ar: 'حركة نموذجية', caliber: 'manual-01', cases: ['case'], dials: ['dial'], hands: ['hands'], functions: [], quote_minor: 15000, currency: 'USD' };
  return {error:key==='directory-choice'||key==='movement-selection'?state.privateError:null,data:!read||((state.pending||state.error)&&(!state.listOnly||key==='official-directory'))?undefined:key==='official-directory'?{items:[business],total:1000,next_after:'next'}:key==='movement-options'?{items:[movement],total:1000,next_after:null}:key==='official-business'?business:key==='movement-option'?{item:{...movement,id:'pinned-movement',caliber:'PINNED-CALIBER'}}:{choice:state.pinned?{organization_id:brand,capability:'maintenance',purpose:'servicing',revision:1}:null,selection:state.pinned?{id:'selection',brand_id:brand,option_id:'pinned-movement',option_revision:1,revision:1,configuration:{case:'PRIVATE-CASE',dial:'PRIVATE-DIAL',hands:'PRIVATE-HANDS',functions:[]},status:'manual_review',quote_impact:{minor:15000,currency:'USD'}}:null},isPending:state.pending&&(!state.listOnly||key==='official-directory'),isError:state.error&&(!state.listOnly||key==='official-directory'),isSuccess:!state.pending&&!state.error,isFetching:false,refetch:vi.fn()};
}}));
vi.mock('@tanstack/react-query',()=>({useQueryClient:()=>({setQueryData:vi.fn()}),useMutation:()=>({mutate:vi.fn(),reset:vi.fn()}),useQuery:({queryKey}:{queryKey:string[]})=>({data:queryKey[0]==='l08-drafts'?{items:[]}:undefined,isPending:false,isError:false}),useInfiniteQuery:()=>({data:{pages:[{status:'available',data:{items:[],next_after:null}}]},isPending:false,isError:false})}));
vi.mock('@/shell/foundation/path',()=>({usesFoundationShell:()=>true}));
import { ApiError } from '@/lib/api/client';
import Directory from './view';
import RequestDrafts from '../request-drafts/request-drafts';
beforeEach(() => { state.locale = 'en'; state.pending = false; state.error = false; state.commandPending=false;state.pinned=false;state.listOnly=false;state.privateError=null; });
it.each(['en', 'ar'] as const)('composes the directory and movement form inside one shared header in %s', locale => {
  state.locale = locale;
  const html = renderToStaticMarkup(createElement(Directory));
  expect(html.match(/<h1\b/g)).toHaveLength(1);
  expect(html).toContain('bt-page-header');
  expect(html).toContain(locale === 'en' ? en.title : ar.title);
  expect(html).toContain('role="radiogroup"');
  expect(html).toContain('aria-checked="true"');
  expect(html).toContain('bt-card');
  expect(html).toContain('Synthetic official brand');
  expect(html).toContain('manual-01');
  expect(html).toContain('bt-button');
  expect(html.match(/type="submit"/g)).toHaveLength(2);
  if (locale === 'en') expect(html).toContain(movementEn.save);
});
it.each(['pending', 'error'] as const)('uses the shared directory %s face', phase => {
  state.pending = phase === 'pending'; state.error = phase === 'error';
  const html = renderToStaticMarkup(createElement(Directory));
  expect(html).toContain('bt-state');
  expect(html).toContain(`data-kind="${phase === 'pending' ? 'loading' : 'error'}"`);
});
it.each(['en', 'ar'] as const)('keeps request draft controls, native POST and translated header in %s', locale => {
  state.locale = locale;
  const html = renderToStaticMarkup(createElement(RequestDrafts));
  expect(html.match(/<h1\b/g)).toHaveLength(1);
  expect(html).toContain(locale === 'en' ? requestEn.title : requestAr.title);
  expect(html).toContain('method="post"');
  for (const name of ['kind', 'brand_id', 'watch_context', 'watch_reference', 'scope_intent', 'notes']) expect(html).toContain(`name="${name}"`);
  expect(html).toContain('ui-textarea');
});

it('uses server totals and real page controls rather than a loaded length',()=>{
  const html=renderToStaticMarkup(createElement(Directory));
  expect(html).toContain('1,000');
  expect(html).toContain(en.more);
  expect(html).not.toContain('<main');
  expect(html).not.toContain('<select');
});
it('keeps the same translation keys for all directory and movement states',()=>{
  expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort());
});

it('opens the content when the shared shell has adopted the route',()=>{
  const html=renderToStaticMarkup(createElement(DirectoryAvailability,null,createElement('p',null,'directory-content')));
  expect(html).toContain('directory-content');
});
it.each([['250.01',25001],['٢٥٠٫٠١',25001],['0.01',1],['0',0]])('accepts exact dollar input %s',(text,cents)=>{
  expect(usdCents(text as string)).toBe(cents);
});
it.each(['1,00','1.001','-1','1e3','10000000000'])('rejects ambiguous or invalid dollar input %s',text=>{
  expect(()=>usdCents(text)).toThrow(RangeError);
});
it('shows exact cents with explicit digit systems in each language',()=>{
  expect(formatMinor(25001,'USD','en')).toBe('250.01 USD');
  expect(formatMinor(25001,'USD','ar')).toBe('٢٥٠٫٠١ USD');
});

it('pins a saved movement outside the current page without rebinding its requirements',()=>{
  state.pinned=true;
  const html=renderToStaticMarkup(createElement(Directory));
  expect(html).toContain('PINNED-CALIBER');
  expect(html).toContain('value="PRIVATE-CASE"');
  expect(html).toContain('value="pinned-movement"');
});
it('freezes selected movement requirements while a save is pending',()=>{
  state.commandPending=true;
  const html=renderToStaticMarkup(createElement(Directory));
  const fields=html.match(/<input[^>]+>/g)??[];
  expect(fields.length).toBeGreaterThanOrEqual(4);
  for(const field of fields)expect(field).toContain('disabled');
});

it.each(['pending','error'] as const)('retains the selected movement while the directory page is %s',phase=>{
  state[phase]=true;state.listOnly=true;
  // Only the list request changes; selected business and movement answers stay available.
  const html=renderToStaticMarkup(createElement(Directory));
  expect(html).toContain('manual-01');
  expect(html).toContain('directory-detail');
  expect(html).toContain('directory-columns');
});

it.each([401,403,404])('suppresses retained buyer answers after denial %s',status=>{
  state.pinned=true;
  state.privateError=new ApiError(status,'forbidden','');
  const html=renderToStaticMarkup(createElement(Directory));
  expect(html).not.toContain('PRIVATE-CASE');
  expect(html).not.toContain('PRIVATE-DIAL');
  expect(html).not.toContain('PRIVATE-HANDS');
  expect(html).not.toContain('directory-restored');
  expect(html).not.toContain('movement-snapshot');
  expect(html).not.toContain(en.saved);
});
