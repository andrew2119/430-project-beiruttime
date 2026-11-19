import {afterEach,expect,it,vi} from 'vitest';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {LocaleContext,useLocale} from '@/shell/locale-context';
import {applyLocale,captureLocaleLink,localeForLink} from '@/shell/locale-change';
import {stripLocale} from '@/shell/paths';
afterEach(()=>vi.unstubAllGlobals());
function LocaleProbe(){return createElement('p',null,useLocale('ar'));}
it('keeps the supplied initial locale when a consumer is rendered outside the provider',()=>expect(renderToStaticMarkup(createElement(LocaleProbe))).toContain('ar'));
it('prefers the live locale context over an old initial server prop',()=>expect(renderToStaticMarkup(createElement(LocaleContext,{value:'en'},createElement(LocaleProbe)))).toContain('en'));
it('changes language in place without serializing any form, private file or operation state',()=>{
 const replaceState=vi.fn();
 const browser={location:{origin:'http://localhost',pathname:'/en/seller/auctions',search:'?filter=%D8%B3&draft=own-reference',hash:'#reserve'},history:{replaceState},document:{cookie:'',documentElement:{lang:'en',dir:'ltr'}}};
 const memory={reserve:'٤٥٠٠٫٢٥',password:'private-fixture',file:new Uint8Array([1,2]),operation:{key:'same-operation'}};
 const file=memory.file,operation=memory.operation;
 applyLocale('ar',browser);
 expect(browser.document.documentElement).toEqual({lang:'ar',dir:'rtl'});expect(browser.document.cookie).toContain('bt-locale=ar');
 expect(replaceState).toHaveBeenCalledWith(null,'','/ar/seller/auctions?filter=%D8%B3&draft=own-reference#reserve');
 expect(JSON.stringify(replaceState.mock.calls)).not.toContain('private-fixture');
 expect(memory.file).toBe(file);expect(memory.operation).toBe(operation);expect(memory.reserve).toBe('٤٥٠٠٫٢٥');
 applyLocale('en',browser);expect(memory.file).toBe(file);expect(memory.operation).toBe(operation);
});
it.each(['http://other.test/ar/seller/auctions','http://localhost/ar/checkout','javascript:alert(1)','http://'])('does not turn an unrelated link into a locale action: %s',href=>expect(localeForLink(href,{origin:'http://localhost',pathname:'/en/seller/auctions'})).toBeNull());
it('recognizes only a same-page locale link and leaves existing query state in place',()=>expect(localeForLink('/ar/seller/auctions?new=ignored',{origin:'http://localhost',pathname:'/en/seller/auctions'})).toBe('ar'));
it('captures an old dedicated locale link before its per-form navigation handler',()=>{
 class Target {closest(){return {href:'http://localhost/ar/seller/auctions'};}}
 vi.stubGlobal('Element',Target);
 const preventDefault=vi.fn(),stopImmediatePropagation=vi.fn(),change=vi.fn();
 const event={button:0,target:new Target(),preventDefault,stopImmediatePropagation} as unknown as MouseEvent;
 captureLocaleLink(event,change,{origin:'http://localhost',pathname:'/en/seller/auctions'});
 expect(preventDefault).toHaveBeenCalledOnce();expect(stopImmediatePropagation).toHaveBeenCalledOnce();expect(change).toHaveBeenCalledWith('ar');
});
it.each([{button:1},{button:0,metaKey:true},{button:0,ctrlKey:true},{button:0,shiftKey:true},{button:0,altKey:true}])('does not take over modified or non-primary activation %j',properties=>{
 const change=vi.fn();captureLocaleLink(properties as unknown as MouseEvent,change,{origin:'http://localhost',pathname:'/en/seller/auctions'});expect(change).not.toHaveBeenCalled();
});
it('normalizes only the locale prefix for route-focus identity',()=>expect(stripLocale('/en/seller/auctions')).toBe(stripLocale('/ar/seller/auctions')));
