export type ImportLocale = 'en'|'ar';

/** Only language links for the current import may keep this document mounted. */
export function importLanguageTarget(current: URL, target: URL): ImportLocale|null {
 const route = /^\/(en|ar)\/seller\/import\/?$/;
 const match = target.pathname.match(route);
 if (!route.test(current.pathname) || !match || target.origin !== current.origin
     || target.search !== current.search || target.hash !== current.hash) return null;
 return match[1] as ImportLocale;
}

export function retainImportLanguage(event: MouseEvent, current: URL, anchor: HTMLAnchorElement, change: (locale: ImportLocale, url: URL)=>void) {
 if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
     || anchor.hasAttribute('download') || (anchor.target && anchor.target !== '_self')) return;
 const target = new URL(anchor.href, current);
 const locale = importLanguageTarget(current, target);
 if (!locale) return;
 event.preventDefault();
 event.stopImmediatePropagation();
 change(locale, target);
}
