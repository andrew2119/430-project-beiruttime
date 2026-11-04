import { describe, expect, it } from 'vitest';
import { defaults, exactMoney, readSearch, searchRangeError, updateSearch, writeSearch } from './url-state';
import { publicImageURL } from './photo';
describe('public URL and exact currency contract',()=>{
  it('round trips known Arabic filters and drops unknown parameters',()=>{
    const state={...defaults,q:'رولكس ٣٦',brand:'Rolex',sort:'price_asc',cursor:'position'};
    expect(readSearch(new URLSearchParams(writeSearch(state)))).toEqual(state);
    expect(writeSearch(readSearch(new URLSearchParams('secret=x&q=watch')))).toBe('q=watch');
    expect(updateSearch(state,{brand:'Omega'}).cursor).toBe('');
  });
  it('validates ranges before requesting market data',()=>{
    expect(searchRangeError({...defaults,min_minor:'١٠٠',max_minor:'٩٩'})).toBe(true);
    expect(searchRangeError({...defaults,min_minor:'۱۰۰',max_minor:'۱۰۰'})).toBe(false);
    for(const value of ['NaN','Infinity','1.5','-1','1e2','9000000000000001']) expect(searchRangeError({...defaults,min_minor:value})).toBe(true);
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
