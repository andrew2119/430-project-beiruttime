import {describe,it,expect} from 'vitest';
import {parseMaximum,formatMinor} from './money';
describe('private maximum exact input',()=>{
  it('normalizes Arabic/Persian digits without float conversion',()=>{
    expect(parseMaximum('٤٥٠٠٫٠١')).toBe(450001);
    expect(parseMaximum('۴۵۰۰.۰۱')).toBe(450001);
    expect(parseMaximum('90000000000000.00')).toBe(9_000_000_000_000_000);
  });
  it('rejects ambiguous, negative, exponent and unsafe amounts',()=>{
    for(const value of ['','-1','0','1e3','1,000','١٬٠٠٠','1.001','NaN','Infinity','90000000000000.01']) expect(parseMaximum(value)).toBeNull();
  });
  it('formats the last exact cent without rounding via binary floats',()=>{
    expect(formatMinor(Number.MAX_SAFE_INTEGER,'USD','en')).toContain('.91 USD');
    expect(formatMinor(16000,'USD','en')).toContain('160.00 USD');
    expect(formatMinor(-1,'USD','ar')).toBe('—');
  });
});

it.each([
  ['en','latn','90,071,992,547,409.91 USD','0.01 USD'],
  ['ar','arab','٩٠٬٠٧١٬٩٩٢٬٥٤٧٬٤٠٩٫٩١ USD','٠٫٠١ USD'],
] as const)('formats exact cents and Beirut civil dates with %s digits',async(locale,numberingSystem,large,cent)=>{
  expect(formatMinor(Number.MAX_SAFE_INTEGER,'USD',locale)).toBe(large);
  expect(formatMinor(1,'USD',locale)).toBe(cent);
  const {buyerDateFormatter}=await import('./buyer-date');
  const formatter=buyerDateFormatter(locale);
  expect(formatter.resolvedOptions()).toMatchObject({numberingSystem,timeZone:'Asia/Beirut'});
  const parts=formatter.formatToParts(new Date('2030-01-01T10:45:00Z'));
  expect(parts.find(part=>part.type==='minute')?.value).toBe(locale==='ar'?'٤٥':'45');
});
