import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe,it,expect,vi } from 'vitest';
import en from '../../../../web/features/care-progress/en.json';
import ar from '../../../../web/features/care-progress/ar.json';
const context = vi.hoisted(()=>({locale:'en' as 'en'|'ar',fingerprint:'current'}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:context.fingerprint})}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>context.locale}));
import { PageReadProvider } from '../../../../web/lib/page-speed/provider';
import CareProgress, { ProgressContent } from '../../../../web/features/care-progress/view';
describe('progress entry',()=>{
  it('has complete matching translation keys',()=>{expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());for(const value of Object.values(ar)) expect(value.length).toBeGreaterThan(0);});
  for(const locale of ['en','ar'] as const) it(`renders the canonical named form in ${locale}`,()=>{
    context.locale=locale;context.fingerprint='current';
    const html=renderToStaticMarkup(<PageReadProvider><ProgressContent fingerprint={context.fingerprint}/></PageReadProvider>), t=locale==='ar'?ar:en;
    expect(html).toContain(t.title);expect(html).toContain(t.job);expect(html).toContain('progress-job');expect(html).not.toContain('<main');
  });
  for(const locale of ['en','ar'] as const) it(`renders unavailable without a read scope on the current route in ${locale}`,()=>{
    context.locale=locale;context.fingerprint='current';
    const html=renderToStaticMarkup(<CareProgress/>), t=locale==='ar'?ar:en;
    expect(html).toContain(t.unavailable);expect(html).not.toContain('progress-job');expect(html).not.toContain('<main');
  });
  it('clears the private entry on missing current access',()=>{
    context.locale='en';context.fingerprint='';
    expect(renderToStaticMarkup(<PageReadProvider><ProgressContent fingerprint={context.fingerprint}/></PageReadProvider>)).toContain(en.denied);
  });
});
