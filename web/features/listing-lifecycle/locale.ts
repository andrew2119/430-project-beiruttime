// Refresh the same internal route so the root locale and shell can update while
// the form keeps its component identity. Never submit on a language click.
export function retainLocaleNavigation(doc: Document, win: Window, refresh: () => void) {
  const click = (event: MouseEvent) => {
    const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a.locale-control') : null;
    if (!anchor || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const destination = new URL(anchor.href, win.location.href);
    const current = new URL(win.location.href);
    const strip = (path: string) => path.replace(/^\/(en|ar)(?=\/|$)/, '');
    const locale = /^\/(en|ar)(?=\/|$)/.exec(destination.pathname)?.[1];
    if (!locale || destination.origin !== current.origin || strip(destination.pathname) !== strip(current.pathname)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    destination.search = current.search;
    destination.hash = current.hash;
    doc.cookie = `bt-locale=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
    win.history.replaceState(win.history.state, '', destination);
    refresh();
  };
  doc.addEventListener('click', click, true);
  return () => doc.removeEventListener('click', click, true);
}
