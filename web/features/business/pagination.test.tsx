import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach,describe,expect,it,vi } from 'vitest';
import { staffWorkspaceFixture } from '../../../tests/lanes/L20/BUSINESS/workspace-fixtures';
const request=vi.hoisted(()=>vi.fn());
vi.mock('./transport',()=>({businessRequest:request}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null}));
vi.mock('next/navigation',()=>({usePathname:()=>'/business'}));
import { pagedRequest,PageControls } from './pagination';
beforeEach(()=>request.mockReset());
describe('bounded workspace reads',()=>{
  it.each([0,1,1000])('requests real server pages and totals for %i rows',async total=>{
    const answer=staffWorkspaceFixture(1,total);request.mockResolvedValue(answer);
    expect(await pagedRequest('/v2/businesses',1,false)).toEqual(answer);
    expect(request).toHaveBeenCalledWith('/v2/businesses?page=1&page_size=25',{},false);
    const html=renderToStaticMarkup(<PageControls answer={answer} change={vi.fn()} />);
    expect(html).toContain('Total records:');
    expect(html.match(/disabled=""/g)?.length).toBe(total<=25?2:1);
  });
  it.each([
    {items:[]}, {...staffWorkspaceFixture(1,1),total:-1},
    {...staffWorkspaceFixture(1,1000),page:2},
    {...staffWorkspaceFixture(1,1000),items:Array(26).fill({})},
  ])('rejects incomplete or reordered page metadata',async answer=>{
    request.mockResolvedValue(answer);
    await expect(pagedRequest('/v2/businesses',1)).rejects.toMatchObject({status:503});
  });
  it('keeps permission and timeout responses as errors',async()=>{
    for (const error of [new Error('denied'),new Error('timeout')]) {
      request.mockRejectedValueOnce(error);
      await expect(pagedRequest('/v2/private-reviews',1)).rejects.toBe(error);
    }
  });
});
