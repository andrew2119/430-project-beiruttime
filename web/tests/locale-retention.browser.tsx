import { act, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider, useLocale, useLocaleChange } from '../shell/locale-context';
import { LocaleControl } from '../shell/foundation/locale-control';
import { PageReadProvider } from '../lib/page-speed/provider';
import { SettingsPage } from '../shell/settings';
import { ThemeProvider } from '../shell/theme-provider';

/** Run on the separate browser check host with route hooks and identity reads
 * supplied by deterministic fixtures. No submitted operation is performed. */
export async function checkLocaleRetention(container: HTMLElement) {
  const root = createRoot(container);
  function Draft() {
    const locale = useLocale(), change = useLocaleChange();
    const pending = useRef({ operation_id: 'operation-17' });
    const [query, setQuery] = useState('نور ⌚');
    return <><LocaleControl locale={locale}/><SettingsPage/>
      <form data-pending={pending.current.operation_id} onSubmit={event => event.preventDefault()}>
        <input aria-label="Private password" type="password" defaultValue="test-unsent-password"/>
        <input aria-label="Private file" type="file"/>
        <input aria-label="Unsent filter" value={query} onChange={event => setQuery(event.target.value)}/>
        <button type="button" onClick={() => change('en')}>Reset language</button>
      </form></>;
  }
  const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };
  try {
    await act(async () => { root.render(<ThemeProvider initialTheme="light"><LocaleProvider locale="en"><PageReadProvider><Draft/></PageReadProvider></LocaleProvider></ThemeProvider>); });
    const password = container.querySelector<HTMLInputElement>('input[type="password"]')!;
    const upload = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const filter = container.querySelector<HTMLInputElement>('input[aria-label="Unsent filter"]')!;
    const file = new File(['private fixture'], 'private.txt', { type: 'text/plain' });
    const transfer = new DataTransfer(); transfer.items.add(file); upload.files = transfer.files;
    const selected = upload.files![0];
    const search = window.location.search, hash = window.location.hash;
    for (const via of ['header', 'settings']) {
      await act(async () => {
        const control = via === 'header' ? container.querySelector<HTMLElement>('.bt-locale-control') :
          Array.from(container.querySelectorAll<HTMLElement>('#settings-language button')).find(node => node.textContent === 'العربية');
        assert(control, 'Language control is available'); control!.click();
      });
      assert(document.documentElement.lang === 'ar', 'Language changed');
      assert(container.querySelector('input[type="password"]') === password && password.value === 'test-unsent-password', 'Password node and value retained');
      assert(container.querySelector('input[type="file"]') === upload && upload.files![0] === selected, 'Private file node and selection retained');
      assert(container.querySelector('input[aria-label="Unsent filter"]') === filter && filter.value === 'نور ⌚', 'Filter retained');
      assert(container.querySelector('form[data-pending]')?.getAttribute('data-pending') === 'operation-17', 'Pending reference retained');
      assert(window.location.search === search && window.location.hash === hash, 'Query and fragment retained');
      await act(async () => { Array.from(container.querySelectorAll('button')).find(node => node.textContent === 'Reset language')!.click(); });
    }
  } finally { await act(async () => root.unmount()); }
}
