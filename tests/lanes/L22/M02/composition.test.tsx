import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LocaleContext } from '../../../../web/shell/locale-context';
import DeferredPage from '../../../../web/app/(saved)/saved/deferred-page';
import { copy } from '../../../../web/features/saved-watches/copy';

describe('saved page before shared composition',()=>{
  it.each(['en','ar'] as const)('renders recovery without providers in %s',locale=>{
    const html=renderToStaticMarkup(<LocaleContext value={locale}><DeferredPage/></LocaleContext>);
    expect(html).toContain(copy[locale].compositionPending);
    expect(html).toContain(`/${locale}/account`);
    expect(html).not.toContain('<input');
  });
});
