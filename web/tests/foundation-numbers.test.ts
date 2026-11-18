import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatAmount, formatNumber, numberFormatter } from '@beirut-time/ui/foundation';
import { VALUES, IDENTIFIERS } from './fixtures/worst-case';
afterEach(()=>vi.restoreAllMocks());
describe('explicit English and Arabic digit contract',()=>{
  it('fixes resolved numbering systems for decimal, currency, percent and compact formatters',()=>{
    for (const locale of ['en','ar'] as const) for (const options of [{},{style:'currency',currency:'USD'},{style:'percent'},{notation:'compact'}] satisfies Intl.NumberFormatOptions[]) expect(numberFormatter(locale,options).resolvedOptions().numberingSystem).toBe(locale === 'ar' ? 'arab' : 'latn');
  });
  it('locks zero, one, large and decimal parts in both languages',()=>{
    for (const [locale,zero,one,integer,group,decimal,fraction] of [['en','0','1',['104','233','918'],',','.','01'],['ar','٠','١',['١٠٤','٢٣٣','٩١٨'],'٬','٫','٠١']] as const) {
      const formatter = numberFormatter(locale);
      expect(formatter.formatToParts(0)).toEqual([{type:'integer',value:zero}]);expect(formatter.formatToParts(1)).toEqual([{type:'integer',value:one}]);
      expect(formatter.formatToParts(VALUES.huge)).toEqual([{type:'integer',value:integer[0]},{type:'group',value:group},{type:'integer',value:integer[1]},{type:'group',value:group},{type:'integer',value:integer[2]}]);
      expect(formatter.formatToParts(Number(VALUES.tinyAmount))).toEqual([{type:'integer',value:zero},{type:'decimal',value:decimal},{type:'fraction',value:fraction}]);
    }
    expect(formatNumber(VALUES.publicMinorLimit,'ar')).toBe('٩٬٠٠٠٬٠٠٠٬٠٠٠٬٠٠٠٬٠٠٠');
    expect(formatAmount(VALUES.amount,'en','USD','Missing')).toBe('12,345,678.90 USD');expect(formatAmount(VALUES.amount,'ar','USD','غير متاح')).toBe('١٢٬٣٤٥٬٦٧٨٫٩٠ USD');
  });
  it('keeps negative sign, direction marks and exact currency parts',()=>{
    expect(numberFormatter('en',{style:'currency',currency:'USD'}).formatToParts(-1234.5)).toEqual([{type:'minusSign',value:'-'},{type:'currency',value:'$'},{type:'integer',value:'1'},{type:'group',value:','},{type:'integer',value:'234'},{type:'decimal',value:'.'},{type:'fraction',value:'50'}]);
    expect(numberFormatter('ar',{style:'currency',currency:'USD'}).formatToParts(-1234.5)).toEqual([{type:'literal',value:'\u061c'},{type:'minusSign',value:'-'},{type:'literal',value:'\u200f'},{type:'integer',value:'١'},{type:'group',value:'٬'},{type:'integer',value:'٢٣٤'},{type:'decimal',value:'٫'},{type:'fraction',value:'٥٠'},{type:'literal',value:'\u00a0'},{type:'currency',value:'US$'}]);
    expect(formatNumber(-1234.5,'en')).toBe('-1,234.5');expect(formatNumber(-1234.5,'ar')).toBe('\u061c-١٬٢٣٤٫٥');
    expect(formatNumber(.12,'en',{style:'percent'})).toBe('12%');expect(formatNumber(.12,'ar',{style:'percent'})).toBe('١٢٪\u061c');
  });
  it('remains identical even if a host default chooses the opposite numbering system',()=>{
    const Native = Intl.NumberFormat, before = (['en','ar'] as const).map(locale=>numberFormatter(locale).formatToParts(-VALUES.huge));
    const received:Intl.NumberFormatOptions[] = [];
    vi.spyOn(Intl,'NumberFormat').mockImplementation((locale,options)=>{received.push(options ?? {});const tag = String(locale);return new Native(locale,{numberingSystem:tag === 'ar' ? 'latn' : 'arab',...options});});
    expect((['en','ar'] as const).map(locale=>numberFormatter(locale).formatToParts(-VALUES.huge))).toEqual(before);expect(received.map(options=>options.numberingSystem)).toEqual(['latn','arab']);
  });
  it('omits invalid or missing numbers instead of rendering nonfinite words',()=>{
    for (const value of [null,undefined,NaN,Infinity,-Infinity]) {expect(formatNumber(value,'en')).toBe('—');expect(formatNumber(value,'ar',undefined,'غير متاح')).toBe('غير متاح');}
  });
  it('does not turn identifiers and machine-readable references into formatted numbers',()=>{
    expect(IDENTIFIERS.reference).toBe('Q1682140-MASTER-ULTRA-THIN-PERPETUAL-PINK-GOLD');expect(IDENTIFIERS.url).toContain('IW503602');expect(IDENTIFIERS.file).toContain('2026-11-15');
  });
});
