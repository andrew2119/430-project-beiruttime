import { describe, expect, it } from 'vitest';
import { defaults, dollarsToMinor, requestSearch, exactMoney, readSearch, searchRangeError, updateSearch, writeSearch } from './url-state';
import { publicImageURL } from './photo';
describe('public URL and exact currency contract',()=>{
  it('round trips known Arabic filters and drops unknown parameters',()=>{
    const state={...defaults,q:'رولكس ٣٦',brand:'Rolex',sort:'price_asc',cursor:'position'};
    expect(readSearch(new URLSearchParams(writeSearch(state)))).toEqual(state);
    expect(writeSearch(readSearch(new URLSearchParams('secret=x&q=watch')))).toBe('q=watch');
    expect(updateSearch(state,{brand:'Omega'}).cursor).toBe('');
  });
  it('validates ranges before requesting market data',()=>{
    expect(searchRangeError({...defaults,min_price:'١٠٠',max_price:'٩٩'})).toBe(true);
    expect(searchRangeError({...defaults,min_price:'۱۰۰',max_price:'۱۰۰'})).toBe(false);
    for(const value of ['NaN','Infinity','1.555','-1','1e2','9000000000000001']) expect(searchRangeError({...defaults,min_price:value})).toBe(true);
  });
  it('converts typed dollars exactly and preserves legacy cents links',()=>{
    expect(dollarsToMinor('١٢٥٠٫٥٠')).toBe('125050');
    expect(dollarsToMinor('90000000000000.00')).toBe('9000000000000000');
    expect(dollarsToMinor('90000000000000.01')).toBeNull();
    expect(dollarsToMinor('1e3')).toBeNull();
    const state=readSearch(new URLSearchParams('min_minor=125050'));
    expect(state.min_price).toBe('1250.50');
    expect(requestSearch(state)).toBe('min_minor=125050');
    expect(requestSearch({...defaults,min_price:'0.01',max_price:'5000'})).toBe('min_minor=1&max_minor=500000');
    expect(()=>requestSearch({...defaults,currency:'LBP'})).toThrow();
  });
  it('does not round money through a floating point number',()=>{
    expect(exactMoney('90000000000000.01','USD','en')).toBe('90,000,000,000,000.01 USD');
    expect(exactMoney('4300','USD','en')).toBe('4,300.00 USD');
    expect(exactMoney('NaN','USD','en')).toBe('—');
  });
  it('permits only public media references',()=>{
    expect(publicImageURL('/demo/watches/one.jpg')).toBe('/demo/watches/one.jpg');
    expect(publicImageURL('/api/web/v1/catalog/v1/listings/watch/photos/photo/hero')).toBe('/api/web/v1/catalog/v1/listings/watch/photos/photo/hero');
    for(const value of ['//external/photo','https://external/photo','/api/private/evidence','/demo/watches/../secret','/demo/watches/x?token=secret','/api/web/v1/catalog/v1/media/unscoped'])expect(publicImageURL(value)).toBeNull();
  });
});
