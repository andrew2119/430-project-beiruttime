import { existsSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, expect, it, vi } from 'vitest';

const state=vi.hoisted(()=>({session:false,status:'restoring'}));
vi.mock('next/navigation',()=>({usePathname:()=>'/operations/signals'}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({
  fingerprint:state.session?'current-access':null,roles:state.session?['operator']:['public']
})}));
vi.mock('@/features/identity/session',()=>({
  useSession:()=>state.session?{access_fingerprint:'current-access'}:null,
  useSessionState:()=>state.status,
  refreshSession:vi.fn(), authenticatedRequest:vi.fn()
}));
import { PageReadProvider } from '@/lib/page-speed/provider';
import { authenticatedRequest } from '@/features/identity/session';
import * as reads from './read';
import SignalsView from './view';

const signalRead=vi.spyOn(reads,'signalRead');
const render=()=>renderToStaticMarkup(<PageReadProvider><SignalsView/></PageReadProvider>);
beforeEach(()=>{state.session=false;state.status='restoring';vi.clearAllMocks();});

it.each(['restoring','unavailable','signed-out'])('withholds private reads while access is %s',status=>{
  state.status=status;
  const html=render();
  expect(html).toContain('Signals for independent review');
  if(status==='restoring') {
    expect(html).toContain('Loading private signals');
    expect(html).toContain('aria-busy="true"');
  } else {
    expect(html).toContain(status==='unavailable'?'Signals unavailable':'Access denied');
    expect(html).toContain('role="alert"');
  }
  expect(html).not.toContain('signal-query');
  expect(signalRead).not.toHaveBeenCalled();
  expect(authenticatedRequest).not.toHaveBeenCalled();
});

it('renders the current private view pending inside the shared foundation scope',()=>{
  state.session=true;state.status='authenticated';
  const html=render();
  expect(html).toContain('Signals for independent review');
  expect(html).toContain('id="signal-query"');
  expect(html).toContain('Filter operation references');
  expect(html).toContain('Loading private signals');
  expect(html).toContain('aria-busy="true"');
  expect(html).not.toContain('Signals unavailable');
  expect(signalRead).toHaveBeenCalledWith('current-access',1);
  expect(authenticatedRequest).not.toHaveBeenCalled();
});

it('withholds the route until shared delivery and shell registration are available',()=>{
  expect(existsSync(new URL('../../app/(fraud-signals)/operations/signals/page.tsx',import.meta.url))).toBe(false);
});
