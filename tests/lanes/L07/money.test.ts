import { expect, test } from '../../../web/node_modules/vitest/dist/index.js';
import { parseMinor, money, editableAmount, parseRevision } from '../../../web/features/pricing/money';
test('minor-unit parsing accepts localized digits without guessing separators',()=>{
  expect(parseMinor('٥٠٠٠٫٠٠','USD')).toBe(500000);
  expect(parseMinor('۵۰۰۰.۰۰','USD')).toBe(500000);
  expect(parseMinor('5000','LBP')).toBe(500000);
  for(const value of ['5,000','٥٬٠٠٠','5e3','NaN','Infinity','1.001','-1','0','90000000000.01']) expect(()=>parseMinor(value,'USD')).toThrow();
  expect(parseMinor('1.00','LBP')).toBe(100);
});
test('exact display and editable values retain cents and LBP units',()=>{
  expect(money(515000,'USD','en')).toBe('5,150.00 USD');
  expect(money(1,'USD','en')).toBe('0.01 USD');
  expect(money(9000000000000,'LBP','en')).toBe('90,000,000,000.00 LBP');
  expect(editableAmount(101,'USD')).toBe('1.01');
  expect(parseRevision('٢')).toBe(2);
  expect(()=>parseRevision('1.0')).toThrow();
});
