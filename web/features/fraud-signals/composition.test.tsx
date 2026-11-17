import { existsSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

vi.mock('next/navigation',()=>({usePathname:()=>'/operations/signals'}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/features/identity/session',()=>({
  useSession:()=>({access_fingerprint:'current-access'}),
  useSessionState:()=> 'authenticated',
  refreshSession:vi.fn(), authenticatedRequest:vi.fn()
}));
import SignalsView from './view';

it('renders unavailable in the current shell without mounting a private read',()=>{
  const html=renderToStaticMarkup(<SignalsView/>);
  expect(html).toContain('Signals unavailable');
  expect(html).toContain('role="alert"');
  expect(html).not.toContain('signal-query');
});

it('withholds the route until shared delivery and shell registration are available',()=>{
  expect(existsSync(new URL('../../app/(fraud-signals)/operations/signals/page.tsx',import.meta.url))).toBe(false);
});
