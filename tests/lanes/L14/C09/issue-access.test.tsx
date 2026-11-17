import { renderToStaticMarkup } from '../../../../web/node_modules/react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../../../web/lib/api/client';

const state = vi.hoisted(() => ({ context: {} as Record<string, unknown>, mutate: vi.fn() }));
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => state.context,
  useMutation: () => ({ mutate: state.mutate, isPending: false, isSuccess: false }),
  useQueryClient: vi.fn(),
}));
vi.mock('@/features/identity/session', () => ({ useSession: () => ({ access_fingerprint: 'synthetic' }), authenticatedRequest: vi.fn() }));
vi.mock('@/features/pricing/s2-shared', () => ({
  useQuoteCopy: () => ({ locale: 'en', t: { issue: 'Issue quote', retry: 'Retry' } }),
  QuoteFailure: ({error}: {error?: Error}) => error ? <p role="alert">Access unavailable</p> : null,
}));
import { Issue } from '../../../../web/features/brand-quotes/page';

const data = { diagnosis: 'Private diagnosis', lines: [{id:'line-one',label:'Private assessed line'}] };
const render = () => renderToStaticMarkup(<Issue kind="brand" contextQuery="source_revision=4" suffix="" onSaved={vi.fn()}/>);

describe('assessment context access', () => {
  it.each([401,403,404,409])('removes private context after a successful read then denial %s', status => {
    state.context = {data,isPending:false,isError:false,isFetching:false};
    expect(render()).toContain('Private diagnosis');
    expect(render()).toContain('Private assessed line');
    state.context = {data,isPending:false,isError:true,isFetching:false,error:new ApiError(status,'denied','')};
    const denied = render();
    expect(denied).not.toContain('Private diagnosis');
    expect(denied).not.toContain('Private assessed line');
    expect(denied).not.toContain('<form');
    expect(denied).toContain('Access unavailable');
  });
  it.each(['failure','refresh'])('disables issuance during context %s and restores it after verification', phase => {
    state.context = {data,isPending:false,isError:phase==='failure',isFetching:phase==='refresh',error:phase==='failure'?new ApiError(503,'unavailable',''):null};
    const blocked = render();
    expect(blocked).toContain('Private diagnosis');
    expect(blocked).toMatch(/<button[^>]*disabled=""[^>]*>Issue quote/);
    state.context = {data,isPending:false,isError:false,isFetching:false};
    expect(render()).toMatch(/<button(?![^>]*disabled)[^>]*>Issue quote/);
  });
});
