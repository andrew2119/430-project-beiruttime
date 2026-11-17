/** One same-document query update preserves unrelated values and the hash.
 * It never changes the path or document language, starts a load or keys a component. */
export function replacePageQuery(values:Record<string,string>) {
  const url = new URL(window.location.href);
  for (const [name,value] of Object.entries(values)) url.searchParams.set(name,value);
  window.history.replaceState(null,'',url);
  return url;
}
