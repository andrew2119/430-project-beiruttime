import { IDENTIFIERS, NAMES, TEXT } from '@/tests/fixtures/worst-case';
import { pageOf } from '@/internal/components/model';
import type { DemoAnswer, DemoRequest } from './reads';
/** Explicit synthetic copy, never a watch price, auction clock or market answer. */
export function demoAnswer(request:DemoRequest,now:number):DemoAnswer {
  const total = request.mode === 'empty' ? 0 : request.mode === 'one' ? 1 : request.mode === 'thousand' ? 1000 : request.mode === 'worst' ? 13 : 3;
  const titles = request.mode === 'demo' ? ['Watch reference example','Case and dial example','Collector notes example'] : [TEXT.titleAtLimit,TEXT.arabicTitle,NAMES.emojiOnly,TEXT.unbroken,TEXT.literalMarkup];
  const items = Array.from({length:total},(_,index)=>({id:`page-example-${index+1}`,title:titles[index%titles.length],reference:IDENTIFIERS.reference}));
  const page = pageOf(items,request.page);
  return {items:page.items,total:page.total,page:page.page,pages:page.pages,servedAt:now};
}
