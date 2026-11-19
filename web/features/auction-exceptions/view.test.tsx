import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({locale:'en' as 'en'|'ar'}));
vi.mock('@/shell/locale-context', () => ({useLocale:() => state.locale}));
vi.mock('@/features/identity/session', () => ({useSession:() => ({access_fingerprint:'current-access'})}));
import AuctionExceptions, { type Connection } from './view';
import { copy } from './copy';
const connection: Connection = {
  context:{subject_id:'auction',watch_id:'watch',actor_id:'operator',organization_id:'business',expected_revision:4,quote_id:'quote',quote_revision:2,policy_revision:1,assignment_revision:3},
  submit:vi.fn(),
};
describe('private exception view', () => {
  it('never renders a connected form when access is denied or unavailable', () => {
    for (const access of ['denied','unavailable','loading','empty'] as const) {
      const html = renderToStaticMarkup(<AuctionExceptions connection={connection} access={access}/>);
      expect(html).not.toContain('<form');
      expect(html).not.toContain('textarea');
      if (access !== 'loading') expect(html).toContain(`href="/${state.locale}/inbox"`);
    }
    expect(connection.submit).not.toHaveBeenCalled();
  });
  it('renders canonical fields only with explicit ready access in both languages', () => {
    for (const locale of ['en','ar'] as const) {
      state.locale = locale;
      const html = renderToStaticMarkup(<AuctionExceptions connection={connection} access="ready"/>);
      expect(html).toContain(copy[locale].title);
      expect(html).toContain(copy[locale].intro);
      expect(html).toContain(copy[locale].action);
      expect(html).toContain(copy[locale].reason);
      expect(html).toContain(copy[locale].submit);
      expect(html).toContain('<form');
      expect(html).toContain('textarea');
      expect(html).toContain('role="radiogroup"');
      expect(html).not.toContain('localStorage');
    }
  });
});
