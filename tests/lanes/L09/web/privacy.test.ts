import { expect, it } from 'vitest';
import { freshData } from '@/features/moderation/privacy';

const privateRecord={evidence:'PRIVATE CASE EVIDENCE'};
it('only paints a settled current-scope response',()=>{
  expect(freshData({data:privateRecord,isFetching:false,error:null})).toBe(privateRecord);
});
it('never previews a cached record during current assignment revalidation',()=>{
  expect(freshData({data:privateRecord,isFetching:true,error:null})).toBeUndefined();
});
it('never previews a cached record after current access is denied',()=>{
  expect(freshData({data:privateRecord,isFetching:false,error:new Error('forbidden')})).toBeUndefined();
});
