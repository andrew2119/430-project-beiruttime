import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
vi.mock('next/navigation',()=>({usePathname:()=>'/en/seller/listings/sample',useSearchParams:()=>new URLSearchParams()}));
import { Failure } from './components';
import { copy } from './copy';
function render(locale:'en'|'ar',status:number,code:string){return renderToStaticMarkup(createElement(Failure,{locale,t:copy(locale),error:new ApiError(status,code,''),retry:()=>{}}));}
describe('published revision failure copy',()=>{
  it.each(['en','ar'] as const)('explains a denied publication/commitment guard in %s',locale=>{
    const t=copy(locale),html=render(locale,409,'listing_frozen');
    expect(html).toContain(t.revisionBlocked);expect(html).toContain(t.errorTitle);expect(html).not.toContain(t.editPending);
  });
  it.each(['en','ar'] as const)('does not claim no source change after uncertain finalization in %s',locale=>{
    const t=copy(locale),html=render(locale,503,'edit_pending');
    expect(html).toContain(t.editPending);expect(html).not.toContain(t.revisionBlocked);
  });
  it('distinguishes sale-method conversion from a temporary dependency failure',()=>{
    expect(render('en',409,'sale_mode_frozen')).toContain(copy('en').saleModeFrozen);
  });
});
