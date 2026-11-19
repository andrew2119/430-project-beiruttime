import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { copy } from '../../../../web/features/reduction/copy';
import { PageReadProvider } from '../../../../web/lib/page-speed/provider';
import declaration from '../../../../web/features/reduction/delivery-contract.json';
import { recordRead } from '../../../../web/features/reduction/api';
import { shellForPath } from '../../../../web/shell/foundation/path';
import pages from '../../../../web/lib/page-speed/pages.json';

const state = vi.hoisted(() => ({ locale: 'en' as 'en' | 'ar' }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => state.locale }));
import { RecordForm } from '../../../../web/features/reduction/view';
import ReductionError from '../../../../web/app/(reduction)/care/reduction/error';

describe('reduction shared composition', () => {
  // Connected route adoption belongs to the shared foundation change.
  it.skipIf(shellForPath(declaration.route, null) !== 'foundation').each(['/care/reduction', '/en/care/reduction', '/ar/care/reduction'])('adopts the root read scope on direct load and navigation to %s', path => {
    expect(shellForPath(path, null)).toBe('foundation');
    expect(shellForPath('/internal/page', path)).toBe('foundation');
  });
  it.skipIf(!pages.some(page => page.route === declaration.route))('registers the exact declaration in the consumed page table', () => {
    expect(pages.find(page => page.route === declaration.route)).toEqual(declaration);
  });
  it('requires the actual shared read scope before opening private records', () => {
    expect(() => renderToStaticMarkup(<RecordForm binding={{record:'record', organization:'business'}} access="access" onPending={() => {}}/>))
      .toThrow('Page reads require the shared page scope');
  });
  it.each(['en', 'ar'] as const)('opens the private form under the canonical read provider in %s', locale => {
    state.locale = locale;
    const markup = renderToStaticMarkup(<PageReadProvider>
      <RecordForm binding={{record:'record', organization:'business'}} access="access" onPending={() => {}}/>
    </PageReadProvider>);
    expect(markup).toContain(copy[locale].loading);
    expect(markup).not.toContain('<main');
  });
  it('keeps the proposed registration bound to the mounted private read', () => {
    expect(Object.keys(declaration).sort()).toEqual(['route', 'file', 'view', 'kind', 'reason', 'content', 'read', 'proof'].sort());
    expect(declaration.file).toBe('web/app/(reduction)/care/reduction/page.tsx');
    expect(declaration.view).toBe('web/features/reduction/view.tsx');
    expect(declaration.content).toBe('[data-page-answer]');
    expect(declaration.reason.trim()).not.toBe('');
    expect(declaration.route).toBe('/care/reduction');
    expect(declaration.read).toBe(recordRead('record', 'business', 'access').key[0]);
    expect(declaration.kind).toBe('reads');
    expect(declaration.proof).toBe('owed');
  });
  it.each(['en', 'ar'] as const)('provides route recovery in %s without reading private facts', locale => {
    state.locale = locale;
    const markup = renderToStaticMarkup(<ReductionError reset={() => {}}/>);
    expect(markup).toContain(copy[locale].unavailable);
    expect(markup).toContain(copy[locale].unavailableBody);
    expect(markup).toContain(copy[locale].refresh);
    expect(markup).toContain(`href="/${locale}/inbox"`);
    expect(markup).toContain(copy[locale].support);
    expect(markup).not.toContain('<main');
  });
});
