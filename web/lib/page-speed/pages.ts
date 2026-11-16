import definitions from './pages.json';
import { shellPath } from '@/shell/foundation/path';
import type { ReadScope } from './scope';
import { warmPageRead } from './definition';
const pages = Object.freeze(definitions.map(page=>Object.freeze(page)));
/** Exact reviewed routes only. Being under the shell prefix grants no warming. */
export function pageFor(address:string) {
  let url:URL;
  try {url = new URL(address,'https://beirut-time.invalid');} catch {return null;}
  if (url.origin !== 'https://beirut-time.invalid' || url.hash || /[\\\u0000-\u0020]/.test(address)) return null;
  return pages.find(page=>page.route === shellPath(url.pathname)) ?? null;
}
export async function warmPageAnswers(address:string,scope:ReadScope) {
  const page = pageFor(address);if (!page || !scope.valid() || page.read !== 'page-demo') return;
  const {demoRead, demoRequest} = await import('@/internal/page/reads');
  if (!scope.valid()) return;
  const query = new URL(address,'https://beirut-time.invalid').searchParams;
  await warmPageRead(scope,demoRead(demoRequest(query.get('data'),query.get('page'))));
}
