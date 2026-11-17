import { replacePageQuery } from '@/lib/page-speed/address';
import { reviewWatches, type ReviewDataMode } from '../../tests/fixtures/worst-case';
export type BoardLocale = 'en'|'ar';
export const DATA_MODES = ['demo','worst','empty','one','thousand'] as const;
export const PAGE_SIZE = 12;
export const COMPONENT_STATES = {
  button:['idle','hover','pressed','focus-visible','busy','disabled','success'],
  link:['idle','focus-visible','disabled'], label:['associated','missing','long'], input:['empty','filled','required','readonly','disabled','error'], textarea:['filled','readonly','disabled','error'],
  checkbox:['off','on','disabled','error'],radio:['off','on','disabled'],switch:['off','on','disabled'],select:['closed','open','search','empty','disabled','error','loading','retry'],
  segmented:['selected','count-zero','count-one','count-huge','disabled','keyboard','rtl'],dialog:['closed','open','wide','nested','closing','reopen','keyboard'],
  'sheet-bottom':['open','drag','flick','resist','regrab'], 'sheet-end':['ltr','rtl','drag'], 'sheet-responsive':['desktop','phone','drag'], 'sheet-phone':['desktop','phone','drag'],
  popover:['closed','open','nested','keyboard','closing'],menu:['closed','open','disabled','radio','destructive','keyboard'],toast:['info','success','warning','error','loading','action','close','drag','keyboard'],
  skeleton:['flat','loading','reduced'],avatar:['initials','graphemes','photo','missing','broken','compact','large'],image:['placeholder','loading','decoded','broken','cached'],
  state:['empty','loading','error'],scroll:['fits','overflows','keyboard'],fold:['open','closed','reversal','keyboard'],list:['empty','one','page','beyond-page','thousand','arrival','exit','undo','reorder','scope-change'],
  numbers:['zero','one','huge','decimal','missing','invalid'],theme:['light','dark','pointer','keyboard','interruption'],navigation:['idle','active','pending','busy','pointer','keyboard'],card:['default'],badge:['neutral','success','warning','error'],
} as const;
export type ComponentId = keyof typeof COMPONENT_STATES;
export function reviewMode(value:unknown):ReviewDataMode {return typeof value === 'string' && DATA_MODES.some(mode=>mode === value) ? value as ReviewDataMode : 'demo';}
export function reviewLocale(value:unknown,fallback:BoardLocale = 'en'):BoardLocale {return value === 'en' || value === 'ar' ? value : fallback;}
export function pageOf<T>(items:readonly T[],requested:number) {
  const pages = Math.max(1,Math.ceil(items.length/PAGE_SIZE)), page = Math.max(0,Math.min(pages-1,Number.isFinite(requested) ? Math.trunc(requested) : 0));
  return {items:items.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE),total:items.length,page,pages};
}
export const boardData = (mode:ReviewDataMode) => reviewWatches(mode).items;
export function persistBoard(mode:ReviewDataMode,locale:BoardLocale) {replacePageQuery({data:mode,locale});document.title = locale === 'ar' ? 'مكوّنات الواجهة · بيروت تايم' : 'Interface components · Beirut Time';}
