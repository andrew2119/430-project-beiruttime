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
