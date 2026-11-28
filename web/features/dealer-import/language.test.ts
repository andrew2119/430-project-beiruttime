import { expect, it } from 'vitest';
import { importLanguageTarget, retainImportLanguage } from './language';

const current=new URL('https://example.invalid/en/seller/import?organization_id=1');
it('handles the language link before document navigation',()=>{
 for(const locale of ['ar','en'] as const){
  let prevented=false,stopped=false;
  const event={button:0,preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;}} as unknown as MouseEvent;
  const anchor={href:`https://example.invalid/${locale}/seller/import?organization_id=1`,target:'',hasAttribute:()=>false} as unknown as HTMLAnchorElement;
  let selected='';
  retainImportLanguage(event,current,anchor,next=>{selected=next;});
  expect(selected).toBe(locale);
  expect(prevented&&stopped).toBe(true);
 }
});
it('leaves other destinations and scope changes to normal navigation',()=>{
 for(const target of ['https://else.invalid/ar/seller/import?organization_id=1','https://example.invalid/ar/seller/import?organization_id=2','https://example.invalid/ar/settings']){
  expect(importLanguageTarget(current,new URL(target))).toBeNull();
 }
});
it('preserves modified-click and new-window navigation',()=>{
 for(const properties of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1},{defaultPrevented:true}]){
  const event={button:0,...properties,preventDefault(){throw Error('Unexpected navigation interception');}} as unknown as MouseEvent;
  const anchor={href:'https://example.invalid/ar/seller/import?organization_id=1',target:'',hasAttribute:()=>false} as unknown as HTMLAnchorElement;
  retainImportLanguage(event,current,anchor,()=>{throw Error('Unexpected language change');});
 }
});
