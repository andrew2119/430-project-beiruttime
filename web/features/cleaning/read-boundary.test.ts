import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams('request=00000000-0000-4000-8000-000000000002')}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/shell/access-context',()=>({useAccessContext:()=>({fingerprint:'current'})}));
vi.mock('@/features/identity/session',()=>({useSession:()=>null,authenticatedRequest:vi.fn()}));

import Cleaning from './view';
import { PageReadProvider } from '@/lib/page-speed/provider';
import { copy } from './copy';

it('requires the shared read scope for a signed-in request',()=>{
  expect(()=>renderToStaticMarkup(createElement(Cleaning))).toThrow('Page reads require the shared page scope');
});

it('mounts the request with the real shared read hook inside its canonical scope',()=>{
  const html=renderToStaticMarkup(createElement(PageReadProvider,null,createElement(Cleaning)));
  expect(html).toContain(copy.en.loading);
  expect(html).not.toContain(copy.en.accepted);
});
