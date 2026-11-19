import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import source from '../../../../packages/contracts-identity/public-profile/fixtures/success-response.v1.json';
import { validateProfile } from '../../../../web/features/seller-profile/validate';
const mounted=vi.hoisted(()=>({locale:'en',query:{data:undefined as unknown,error:undefined as unknown,isPending:false,isFetching:false,isError:false,refetch:()=>{}}}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>mounted.locale}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>mounted.query}));
vi.mock('@/features/seller-profile/read',()=>({useSellerRefresh:()=>{},useSellerRead:()=>mounted.query}));
import SellerProfile from '../../../../web/features/seller-profile/view';
import { ApiError } from '../../../../web/lib/api/client';

describe('public seller response boundary',()=>{
 it('accepts the versioned empty history fixture',()=>{
  expect(validateProfile(source,'seller-1',1).sales.released_count).toBe(0);
 });
 it('rejects cross-subject, page and version responses',()=>{
  expect(()=>validateProfile(source,'other',1)).toThrow();
  expect(()=>validateProfile(source,'seller-1',1,'another-read')).toThrow();
  expect(validateProfile(source,'seller-1',1,'sample-read-1')).toEqual(source);
  expect(()=>validateProfile(source,'seller-1',2)).toThrow();
  expect(()=>validateProfile({...source,schema_version:'unknown'},'seller-1',1)).toThrow();
 });
 it('rejects malformed counts, dates and private assets',()=>{
  for (const change of [{sales:{state:'ready',released_count:-1}},{identity:{...source.identity,member_since:'invalid'}},{identity:{...source.identity,logo:'/media/logo.png'}}]) {
   expect(()=>validateProfile({...source,...change},'seller-1',1)).toThrow();
  }
 });
 it.each(['en','ar'])('renders honest empty history and unavailable reviews in %s',locale=>{
  mounted.locale=locale;
  mounted.query={...mounted.query,data:{...source,reviews:{state:'unavailable',distribution:null}},error:undefined,isPending:false,isFetching:false};
  const html=renderToStaticMarkup(<SellerProfile id="seller-1"/>);
  expect(html).toContain(locale==='ar'?'لا يوجد سجل مبيعات محررة':'No released-sale history');
  expect(html).toContain(locale==='ar'?'المعلومات غير متاحة':'Information unavailable');
  expect(html).not.toContain(locale==='ar'?'لا توجد تقييمات':'No reviews');
 });
 it.each(['en','ar'])('uses canonical loading and page composition in %s',locale=>{
  mounted.locale=locale;
  mounted.query={...mounted.query,data:undefined,error:undefined,isError:false,isPending:true,isFetching:true};
  expect(renderToStaticMarkup(<SellerProfile id="seller-1"/>)).toContain('bt-page-wait');
  mounted.query={...mounted.query,data:source,isPending:false,isFetching:false};
  const html=renderToStaticMarkup(<SellerProfile id="seller-1"/>);
  expect(html).toContain('bt-page-body');
  expect(html).toContain('aria-labelledby="page-title"');
 });
 it.each(['en','ar'])('preserves %s in listing destinations',locale=>{
  mounted.locale=locale;
  mounted.query={...mounted.query,error:undefined,isError:false,isPending:false,isFetching:false,data:{...source,listings:{state:'ready',items:[{id:'watch-1',title:'ساعة Watch ⌚'}],total:1,page:1,page_size:20}}};
  expect(renderToStaticMarkup(<SellerProfile id="seller-1"/>)).toContain(`href="/${locale}/watches/watch-1"`);
 });
 it.each(['en','ar'])('keeps header controls focusable through waiting and failure in %s',locale=>{
  mounted.locale=locale;
  for (const status of [
   {data:source,error:undefined,isPending:false,isFetching:false,isError:false},
   {data:undefined,error:undefined,isPending:true,isFetching:true,isError:false},
   {data:undefined,error:new ApiError(503,'unavailable','read-1'),isPending:false,isFetching:false,isError:true},
  ]) {
   mounted.query={...mounted.query,...status};
   const html=renderToStaticMarkup(<SellerProfile id="seller-1"/>);
   const header=html.slice(html.indexOf('<header'),html.indexOf('</header>'));
   expect(header.match(/<button /g)).toHaveLength(3);
   expect(header).not.toMatch(/<button[^>]*\sdisabled=/);

  }
 });
 it('renders stale response and pending reference',()=>{
  mounted.locale='en';
  mounted.query={...mounted.query,data:undefined,error:new ApiError(409,'stale','read-1'),isError:true};
  expect(renderToStaticMarkup(<SellerProfile id="seller-1"/>)).toContain('Information changed');
  mounted.query={...mounted.query,error:undefined,isError:false,data:{...source,state:'pending',identity:null}};
  expect(renderToStaticMarkup(<SellerProfile id="seller-1"/>)).toContain('sample-read-1');
 });
});
