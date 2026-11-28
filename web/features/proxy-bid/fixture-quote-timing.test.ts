import {expect,it} from 'vitest';
import {quotePreviewExpired,quotePreviewTiming} from './fixture-quote-timing.mjs';

it.each([-1,0,1])('expires the uncommitted quote preview at the server boundary (%i ms)',offset=>{
  const created='2030-01-01T10:00:00Z';
  const preview=quotePreviewTiming(created);
  const deadline=Date.parse(created)+900_000;
  expect(Date.parse(preview.expires_at)).toBe(deadline);
  expect(quotePreviewExpired(preview,new Date(deadline+offset).toISOString())).toBe(offset>=0);
});
