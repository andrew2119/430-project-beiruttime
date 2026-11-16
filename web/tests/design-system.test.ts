import { describe, expect, it, vi } from 'vitest';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { Button, ButtonLink, Input, Label, Checkbox, Radio, Segmented, State, Skeleton } from '@beirut-time/ui';
import { parseTheme, nextTheme, themeCookieString } from '@/lib/theme';
import { canScrollBoxMove } from '../../packages/ui/src/scroll-box';
import { areaForPath, permittedEntries } from '@/shell/navigation';
vi.mock('next/navigation',()=>({usePathname:()=>'/en/watches'}));
const read=(path:string)=>readFileSync(new URL(path,import.meta.url),'utf8');
describe('Beirut Time foundation contract',()=>{
 it('keeps the existing SSR cookie with a two-theme cycle and safe defaults',()=>{
  expect(parseTheme(undefined)).toBe('light');expect(parseTheme('classic')).toBe('light');expect(parseTheme('dark')).toBe('dark');expect(nextTheme('dark')).toBe('light');
  expect(themeCookieString('dark',true)).toBe('bt-theme=dark; Path=/; Max-Age=31536000; SameSite=Lax; Secure');
 });
 it('retains native button/form/label semantics and existing variants',()=>{
  const button=renderToStaticMarkup(h(Button,{type:'submit',disabled:true,chonk:true},'Save'));
  expect(button).toContain('type="submit"');expect(button).toContain('disabled');expect(button).toContain('pg-chonk-primary');
  expect(renderToStaticMarkup(h(Button,{className:'button-secondary'},'Cancel'))).toContain('ui-btn-outline');
  expect(renderToStaticMarkup(h(ButtonLink,{href:'/en/watches',variant:'outline'},'Browse'))).toContain('href="/en/watches"');
  expect(renderToStaticMarkup(h(Label,{htmlFor:'email'},'Email'))).toContain('for="email"');
  expect(renderToStaticMarkup(h(Input,{id:'email',name:'email',type:'email',required:true}))).toContain('ui-input');
  expect(renderToStaticMarkup(h(Checkbox,{name:'agree',children:'Agree'}))).toContain('type="checkbox"');
  expect(renderToStaticMarkup(h(Radio,{name:'choice',value:'a',children:'Choice'}))).toContain('type="radio"');
 });
 it('renders the selected segmented state before measurement and translated faces',()=>{
  const markup=renderToStaticMarkup(h(Segmented,{value:'en',onChange:()=>{},options:[{value:'en',label:'English'},{value:'ar',label:'العربية'}],'aria-label':'Language'}));
  expect(markup).toContain('data-seg-active=""');expect(markup).toContain('aria-pressed="true"');expect(markup).toContain('العربية');
  expect(renderToStaticMarkup(h(State,{title:'تعذر التحميل',body:'حاول مجددًا',kind:'error'}))).toContain('pg-face-card');
  expect(renderToStaticMarkup(h(Skeleton,{label:'جارٍ التحميل'}))).toContain('role="status"');
 });
 it('keeps permission filtering exact, with public browsing available to every role',()=>{
  const entries=[{id:'watches',href:'/watches',label:{en:'Watches',ar:'الساعات'},order:1,area:'storefront' as const,roles:['public' as const]},{id:'ops',href:'/operations/dashboard',label:{en:'Operations',ar:'العمليات'},order:2,area:'operator' as const,roles:['operator' as const]}];
  expect(permittedEntries(entries,['buyer']).map(e=>e.id)).toEqual(['watches']);expect(permittedEntries(entries,['operator']).map(e=>e.id)).toEqual(['watches','ops']);
  expect(areaForPath('/ar/seller/listings/123',[{path:'/seller/listings/:id',area:'seller',roles:['private_seller']}])).toBe('seller');
 });
 it('keeps physical arrow scrolling reachable at both RTL edges',()=>{
  const area={scrollTop:0,clientHeight:100,scrollHeight:100,scrollLeft:0,clientWidth:100,scrollWidth:300} as HTMLElement;
  vi.stubGlobal('getComputedStyle',()=>({direction:'rtl'}));
  try {
   expect(canScrollBoxMove(area,[0,-80])).toBe(true);
   expect(canScrollBoxMove(area,[0,80])).toBe(false);
   area.scrollLeft=-200;
   expect(canScrollBoxMove(area,[0,-80])).toBe(false);
   expect(canScrollBoxMove(area,[0,80])).toBe(true);
  } finally {vi.unstubAllGlobals();}
 });
 it('keeps the bordeaux ramp and brand-mark references aligned',()=>{
  const tokens=read('../styles/tokens.css');
  const ramp={50:'97% 0.012 27',100:'91.4% 0.028 28.5',200:'85% 0.055 28',300:'76% 0.09 27.5',400:'66% 0.135 27.5',500:'58% 0.19 27.5',600:'50.6% 0.193 27.7',700:'41.6% 0.148 26.6',800:'35.6% 0.124 26.2',900:'29% 0.1 26',950:'23.3% 0.079 25.8'};
  for(const [step,value] of Object.entries(ramp)){
   expect(tokens).toContain(`--bt-burgundy-${step}: oklch(${value});`);
   expect(tokens).toContain(`--color-bordeaux-${step}: var(--bt-burgundy-${step});`);
  }
  const foundation=read('../styles/foundation.css');
  expect(foundation).toContain('color: var(--color-bordeaux-700)');
  expect(foundation).toContain('[data-theme="dark"] .bt-brand-mark { color: var(--color-bordeaux-400); }');
 });
 it('has one token owner, faithful motion steps, reduced motion and an exact 850px boundary',()=>{
  const tokens=read('../styles/tokens.css'), motion=read('../styles/motion.css');
  expect(tokens).toContain('--ds-motion-theme: 0.45s');expect(tokens).toContain('--ds-motion-image-reveal: 0.18s');expect(tokens).toContain('--bt-touch-target: 44px');expect(tokens).toContain('--bt-phone-control: 36px');
  expect(motion).toContain('@media (prefers-reduced-motion: reduce)');expect(motion).toContain('::view-transition-new(*)');
  expect(read('../shell/theme-provider.tsx')).toContain('doc.startViewTransition(() =>');
  expect(read('../shell/phone-navigation.tsx')).toContain('(max-width: 850px)');expect(read('../styles/mobile.css')).toContain('(max-width: 850px)');
  expect(read('../shell/shell.tsx')).toContain('</div><AppToaster');
  expect(read('../shell/dashboard.tsx')).toContain('className="pg-home-page"');
  expect(read('../styles/mobile.css')).toContain('.pg-home-page .pg-dept-grid { grid-template-columns: minmax(0, 1fr); }');
  expect(read('../../packages/ui/src/button-variants.ts')).not.toContain('use client');
 });
});
