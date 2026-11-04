import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatMinor } from '../../../web/features/movement-option/money.ts';

test('USD cents remain exact for display',()=>{
  assert.match(formatMinor(25000,'USD','en','minor units'),/250\.00/);
  assert.match(formatMinor(1,'USD','en','minor units'),/0\.01/);
  assert.match(formatMinor(0,'USD','en','minor units'),/0\.00/);
});
test('LBP keeps its raw integer instead of inventing an exponent',()=>{
  const amount=25000000;
  assert.equal(formatMinor(amount,'LBP','en','minor units'),`${new Intl.NumberFormat('en-LB').format(amount)} LBP · minor units`);
  assert.equal(formatMinor(amount,'LBP','ar','وحدات صغرى'),`${new Intl.NumberFormat('ar-LB').format(amount)} LBP · وحدات صغرى`);
});
test('non-finite, fractional, negative and unsafe values cannot become prices',()=>{
  for(const value of [Infinity,NaN,.5,-1,Number.MAX_SAFE_INTEGER+1]) assert.throws(()=>formatMinor(value,'USD','en','minor units'),RangeError);
});
