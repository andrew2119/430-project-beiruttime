// Refresh the shared layout's language props without replacing the mounted form.
export function changeRequestLocale(event: MouseEvent, refresh: () => void) {
  const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a.locale-control') : null;
  if (!anchor || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const current = new URL(window.location.href), destination = new URL(anchor.href);
  const language = /^\/(en|ar)(?=\/|$)/.exec(destination.pathname)?.[1];
  const strip = (path: string) => path.replace(/^\/(en|ar)(?=\/|$)/, '') || '/';
  if (destination.origin !== current.origin || !language || strip(destination.pathname) !== strip(current.pathname)) return;
  event.preventDefault();
  event.stopPropagation();
  current.pathname = `/${language}${strip(current.pathname)}`;
  document.cookie = `bt-locale=${language}; Path=/; Max-Age=31536000; SameSite=Lax`;
  const state = { ...window.history.state };
  // Let the shared router restore its current tree against the new URL.
  delete state.__NA;
  delete state._N;
  window.history.replaceState(state, '', current);
  refresh();
}
