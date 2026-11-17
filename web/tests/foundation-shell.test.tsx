import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import type { NavEntry } from '../registry-types';
import { ShellBoundary } from '../shell/shell-boundary';
import { ThemeProvider } from '../shell/theme-provider';
import { ComponentBoard } from '../internal/components/client';
import { PageFrame, PageHeader, PageLoading } from '../shell/foundation/page';
import { shellForPath, usesFoundationShell, shellPath, pageOwnsToasts } from '../shell/foundation/path';
import { AboutPage } from '../shell/foundation/about';
import { HomePage } from '../shell/foundation/home';
import { SettingsPage } from '../shell/settings';
import { LocaleContext } from '../shell/locale-context';
import { StartingPage } from '../internal/page/view';
import { demoAnswer } from '../internal/page/demo-data';
import { TEXT } from './fixtures/worst-case';
const state = vi.hoisted(()=>({client:false,path:'/en/internal/page',phone:false,locale:'en' as 'en'|'ar',answer:undefined as unknown,isFetching:false,isError:false}));
vi.mock('react',async()=>{const real = await vi.importActual<typeof import('react')>('react');return {...real,useSyncExternalStore:(subscribe:unknown,get:()=>unknown,server:()=>unknown)=>state.client ? get() : server()};});
vi.mock('next/navigation',()=>({usePathname:()=>state.path.split('?')[0],useSearchParams:()=>new URLSearchParams(state.path.split('?')[1] ?? ''),useRouter:()=>({prefetch:vi.fn()})}));
vi.mock('next/link',()=>({default:({href,children,prefetch,...props}:Record<string,unknown>)=>{void prefetch;return <a href={String(href)} {...props}>{children as never}</a>;},useLinkStatus:()=>({pending:false})}));
vi.mock('next/dynamic',()=>({default:()=>()=>null}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:null,roles:['public']})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,useSessionState:()=> 'restoring',refreshSession:vi.fn(),signOut:vi.fn()}));
vi.mock('@beirut-time/ui/foundation',async()=>({...await vi.importActual('@beirut-time/ui/foundation'),Toaster:()=> <div data-toast-outlet=""/>}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.answer,isFetching:state.isFetching,isError:state.isError,refetch:vi.fn()})}));
vi.mock('@/shell/locale',()=>({getLocale:async()=>state.locale,getPublicPath:async()=>state.path}));
vi.mock('@/shell/install-prompt-provider',()=>({useInstallPrompt:()=>({canInstall:false,isStandalone:false,isIOS:false})}));
vi.mock('@/registry-loader',()=>({navigation:[]}));
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>undefined})}));
vi.mock('next/font/local',()=>({default:({variable}:{variable:string})=>({variable:variable.replaceAll('-','')})}));
const entries:NavEntry[] = [{id:'home',href:'',label:{en:'Marketplace',ar:'السوق'},order:0,area:'storefront',roles:['public']},{id:'seller-listings',href:'/seller/listings',label:{en:'Selling',ar:'البيع'},order:1,area:'seller',roles:['private_seller']}];
function show(serverPath:string,children:React.ReactNode=<h1>Page</h1>) {return renderToStaticMarkup(<ThemeProvider initialTheme="light"><ShellBoundary serverPath={serverPath} locale={state.locale} entries={entries}><LocaleContext value={state.locale}>{children}</LocaleContext></ShellBoundary></ThemeProvider>);}
beforeEach(()=>{state.client=false;state.phone=false;state.path='/en/internal/page';state.locale='en';state.answer=undefined;state.isFetching=false;state.isError=false;vi.stubGlobal('window',{matchMedia:()=>({matches:state.phone})});vi.stubGlobal('navigator',{onLine:true});});
afterEach(()=>vi.unstubAllGlobals());
describe('exclusive shell owner under bounded server/client snapshots, not a browser hydration proof',()=>{
  it('trusted direct loads select exactly one main/nav/outlet; no first-frame blank shell',()=>{
    for (const path of ['/internal/page','/ar/internal/page','/internal/components']) {const html = show(path);expect(html.match(/<main\b/g)).toHaveLength(1);expect(html).toContain('class="bt-shell"');expect(html).toContain('class="pg-tray bt-shell-content"');expect(html).not.toContain('data-family="legacy"');expect(html).toContain('Restoring your session');if (path !== '/internal/components') expect(html.match(/data-toast-outlet/g)).toHaveLength(1);}
    state.path='/en/internal/page';const old = show('/watches');expect(old.match(/<main\b/g)).toHaveLength(1);expect(old).not.toContain('data-family="legacy"');expect(old).toContain('class="bt-shell"');
  });
  it('committed client crossings in both directions override a persistent root request snapshot',()=>{
    state.client=true;state.path='/ar/internal/page';expect(show('/watches')).toContain('class="bt-shell"');state.path='/en/watches';expect(show('/internal/page')).toContain('class="bt-shell"');
    for (const server of ['/watches','/internal/page']) for (const committed of ['/en/watches','/ar/internal/page']) {state.path=committed;const html=show(server);expect(html.match(/<main\b/g)).toHaveLength(1);expect(html.match(/data-toast-outlet/g)).toHaveLength(1);}
    expect(usesFoundationShell('/watches')).toBe(true);expect(shellForPath('/watches',null)).toBe('foundation');expect(shellPath('/ar/internal/page')).toBe(shellPath('/internal/page'));
  });
  it('the actual accepted board supplies the sole canonical outlet while adopting the new shell',()=>{
    for (const locale of ['en','ar'] as const) {state.locale=locale;const html=show('/internal/components',<ComponentBoard initialMode="one" initialLocale={locale}/>);expect(html.match(/data-toast-outlet/g)).toHaveLength(1);expect(html.match(/<main\b/g)).toHaveLength(1);expect(html.match(/<h1\b/g)).toHaveLength(1);expect(html).toContain('bt-board');}
    expect(pageOwnsToasts('/ar/internal/components')).toBe(true);expect(pageOwnsToasts('/internal/components/other')).toBe(false);
  });
  it('one navigation/profile is composed at a time; the phone trigger is not a nested button',()=>{
    const desktop=show('/internal/page');expect(desktop.match(/class="bt-shell-navigation"/g)).toHaveLength(1);expect(desktop).not.toContain('Selling');
    state.client=true;state.phone=true;const phone=show('/internal/page');expect(phone).not.toContain('class="bt-shell-rail"');expect(phone).toContain('aria-label="Open navigation"');expect(phone).not.toMatch(/<button[^>]*><span[^>]*><button/);
  });
  it('public pages resolve their copy and links from the current language under one shared frame',()=>{
    for (const locale of ['en','ar'] as const) {
      state.locale=locale;
      for (const [path,page,title] of [
        ['/about',<AboutPage key="about"/>,locale === 'ar' ? 'بيروت' : ''],
        ['/',<HomePage key="home" entries={entries}/>,locale === 'ar' ? 'لوحة التحكم' : 'Dashboard'],
        ['/settings',<SettingsPage key="settings"/>,locale === 'ar' ? 'الإعدادات' : 'Settings'],
      ] as const) {
        const html=show(path,page);
        expect(html.match(/<main\b/g)).toHaveLength(1);
        expect(html.match(/<h1\b/g)).toHaveLength(1);
        expect(html.match(/data-toast-outlet/g)).toHaveLength(1);
        expect(html).toContain('bt-page-header hx-wrap hx-sys hx-onpage');expect(html).toContain('hx-head');expect(html).toContain('hx-titlerow');expect(html).toContain(title);
        expect(html).not.toContain(`href="/${locale === 'en' ? 'ar' : 'en'}/account"`);
        if (path === '/about') expect(html).toContain(`href="/${locale}"`);
        if (path === '/settings') {expect(html).toContain('id="settings-language"');expect(html).toContain('bt-segmented');expect(html).not.toContain('proto-set-');expect(html).toContain('bt-settings-index');expect(html).toContain('bt-settings-tabs');expect(html).toContain('hx-tabs');expect(html).toContain('data-look="pane"');expect(html).toContain('hx-tabs-ruler');expect(html).toContain('bt-settings-shot');}
      }
    }
  });
  it('all frame states use the real shared composition with whole words, counts and labeled shapes',()=>{
    const html=renderToStaticMarkup(<PageFrame><PageHeader title={'نور '.repeat(100)} lead="Long content" count="١٠٤٬٢٣٣٬٩١٨" actions={<button type="button">A whole action</button>}/></PageFrame>);expect(html.match(/<h1\b/g)).toHaveLength(1);expect(html).toContain('hx-title');expect(html).toContain('١٠٤٬٢٣٣٬٩١٨');expect(html).not.toContain('title=');const wait=renderToStaticMarkup(<PageLoading label="Loading page"/>);expect(wait).toContain('role="status"');expect(wait.match(/bt-row-skeleton"/g)).toHaveLength(3);
  });
  it('actual starting page keeps retained/empty data visible and only has shapes without an answer',()=>{
    const render=()=>show('/internal/page',<StartingPage locale={state.locale}/>);
    expect(render()).toContain('aria-label="Loading review records"');state.answer=demoAnswer({mode:'empty',page:0},1);let html=render();expect(html).toContain('No review records');expect(html).not.toContain('aria-label="Loading review records"');
    state.answer=demoAnswer({mode:'worst',page:0},2);state.isFetching=true;html=render();expect(html).toContain('Refreshing in the background');expect(html).toContain(TEXT.titleAtLimit);expect(html).not.toContain('aria-label="Loading review records"');state.isFetching=false;state.isError=true;expect(render()).toContain('The last answer is still shown');state.answer=undefined;expect(render()).toContain('Review records are unavailable');
  });
  it('the real page uses every data mode and either language, with native single-choice filtering and complete totals',()=>{
    for (const locale of ['en','ar'] as const) for (const mode of ['demo','worst','empty','one','thousand'] as const) {state.locale=locale;state.path=`/${locale}/internal/page?data=${mode}`;state.answer=demoAnswer({mode,page:0},1);const html=show('/internal/page',<StartingPage locale={locale}/>);expect(html).toContain(locale === 'ar' ? 'dir="rtl" lang="ar"' : 'dir="ltr" lang="en"');expect(html).toContain('role="radiogroup"');expect(html.match(/<h1\b/g)).toHaveLength(1);expect(html).not.toContain('aria-label="Loading review records"');if (mode === 'thousand') expect(html).toContain(locale === 'ar' ? '١٬٠٠٠' : '1,000');if (mode === 'one') expect(html).toContain(locale === 'ar' ? 'مثال واحد' : '1 example');if (mode === 'empty') expect(html).toContain(locale === 'ar' ? 'لا توجد سجلات للمراجعة' : 'No review records');}
  });
  it('navigation, header tabs and both paging states use the same native destination recipe',()=>{
    for (const locale of ['en','ar'] as const) {
      state.locale=locale;state.path=`/${locale}/internal/page?data=worst`;
      for (const page of [0,1]) {
        state.answer=demoAnswer({mode:'worst',page},1);
        const html=show('/internal/page',<StartingPage locale={locale}/>);
        const anchors=(source:string)=>source.match(/<a\b[^>]*>/g) ?? [];
        const navigation=html.match(/<nav class="bt-shell-navigation"[^>]*>(.*?)<\/nav>/)?.[1];
        const header=html.match(/<div class="hx-navrow"[^>]*>(.*?)<\/div>/)?.[1];
        const paging=html.match(/<div class="bt-page-tools"[^>]*>(.*?)<\/div>/)?.[1];
        expect(navigation).toBeDefined();expect(header).toBeDefined();expect(paging).toBeDefined();
        for (const [source,count] of [[navigation,1],[header,2],[paging,2]] as const) {
          const links=anchors(source ?? '');expect(links).toHaveLength(count);
          for (const link of links) {expect(link).toMatch(/class="bt-destination (?:bt-destination-tab )?bt-pressable"/);expect(link).not.toContain('style=');expect(link).toContain('href=');}
        }
        expect(anchors(paging ?? '').filter(link=>link.includes('aria-disabled="true"'))).toHaveLength(1);
      }
    }
  });
  it('the single intentional legacy-visible change is the bilingual default tab-title format',async()=>{
    const {generateMetadata}=await import('../app/layout');state.locale='en';expect((await generateMetadata()).title).toEqual({default:'Time well chosen · Beirut Time',template:'%s · Beirut Time'});state.locale='ar';expect((await generateMetadata()).title).toEqual({default:'للوقت حُسن الاختيار · بيروت تايم',template:'%s · بيروت تايم'});
  });
  it('source owners retain providers and language behavior; scoped imports, demand helper and timing stay singular',()=>{
    const layout=readFileSync(new URL('../app/layout.tsx',import.meta.url),'utf8'), shell=readFileSync(new URL('../shell/foundation/shell.tsx',import.meta.url),'utf8'), globals=readFileSync(new URL('../app/globals.css',import.meta.url),'utf8'), motion=readFileSync(new URL('../styles/bt-motion.css',import.meta.url),'utf8'), request=readFileSync(new URL('../lib/theme-request.ts',import.meta.url),'utf8');
    expect(layout).toContain('<FoundationProviders locale={locale}><ShellBoundary');expect(layout).not.toMatch(/key=\{/);expect(shell).not.toContain('Preferences');expect(shell).not.toContain('bt-locale');expect(globals.match(/bt-shell\.css/g)).toHaveLength(1);expect(motion.match(/--bt-motion-pending: 120ms/g)).toHaveLength(1);expect(request).toContain("import('./theme-transition')");
  });
});

it('canonical headers retain the shared sticky and measured responsive recipes',()=>{
  const read=(file:string)=>readFileSync(new URL(file,import.meta.url),'utf8');
  const header=read('../shell/foundation/page.tsx');
  expect(header).toContain('<StickyHeader wrap={wrap}/>');
  expect(header).toContain('useTitleFit(row)');
  expect(header).toContain('useHeaderTips(wrap)');
  for(const row of ['hx-zone','hx-head','hx-titlerow','hx-ident','hx-tblock','hx-titleline','hx-actions','hx-navrow']) expect(header).toContain(row);
  expect(read('../shell/settings.tsx')).toContain('<HeaderTabs items={sections}');
  expect(read('../styles/page-header.css')).toContain('@container hx (max-width: 30rem)');
  expect(read('../styles/sticky.css')).toContain('position: sticky');
});
