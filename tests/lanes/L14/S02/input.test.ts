import { expect, it } from 'vitest';
import { repairMinor } from '../../../../web/features/repair-quotes/input';
it('retains exact USD cents for English and Arabic input including zero fees',()=>{
 expect(repairMinor('5000.01')).toBe(500001);
 expect(repairMinor('٥٠٠٠٫٠١')).toBe(500001);
 expect(repairMinor('0.00')).toBe(0);
 expect(repairMinor('٩٠٠٠٠٠٠٠٠٠٠٫٠٠')).toBe(9000000000000);
});
it('rejects ambiguous, negative, fractional-cent and excessive amounts',()=>{
 for(const value of ['', '1,000', '1.001', '-1', 'NaN', '1e3', '90000000000.01'])expect(()=>repairMinor(value)).toThrow();
});
