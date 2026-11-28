import { closeSync, mkdirSync, existsSync, openSync, readFileSync, realpathSync, renameSync, writeFileSync, unlinkSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PAGE_TABLE, validatePageTable } from './check-page-contract.mjs';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)),'../..');
/** A read-free internal starting point. A real server-backed screen must add a
 * reviewed shared read, not fill a generated page with pretend market data. */
export function startingFiles(spec) {
  for (const key of ['slug','en','ar','bodyEn','bodyAr','reason']) if (typeof spec[key] !== 'string' || !spec[key].trim()) throw new Error(`Missing ${key}`);
  if (!/^[a-z][a-z0-9-]{0,47}$/.test(spec.slug)) throw new Error('Use one lowercase internal route name');
  const quoted = value=>JSON.stringify(value), route = `/internal/${spec.slug}`, file = `web/app${route}/page.tsx`, view = `web/internal/${spec.slug}/view.tsx`;
  return {entry:{route,file,view,kind:'static',reason:spec.reason,content:'[data-static-page]',read:'none',proof:'owed'},files:{
    [file]:`import type { Metadata } from 'next';\nimport { getLocale } from '@/shell/locale';\nimport { PageView } from '@/internal/${spec.slug}/view';\nexport async function generateMetadata():Promise<Metadata> {return {title:{absolute:(await getLocale()) === 'ar' ? ${quoted(spec.ar+' · بيروت تايم')} : ${quoted(spec.en+' · Beirut Time')}},robots:{index:false,follow:false}};}\nexport default async function Page() {return <PageView locale={await getLocale()}/>;}\n`,
    [view]:`import type { Locale } from '@/lib/i18n';\nimport { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';\nexport function PageView({locale}: {locale:Locale}) {return <PageFrame><PageHeader title={locale === 'ar' ? ${quoted(spec.ar)} : ${quoted(spec.en)}}/><PageBody><p className="bt-text" data-static-page="">{locale === 'ar' ? ${quoted(spec.bodyAr)} : ${quoted(spec.bodyEn)}}</p></PageBody></PageFrame>;}\n`,
    [`web/tests/pages/${spec.slug}.test.tsx`]:`import { expect, it } from 'vitest';\nimport { renderToStaticMarkup } from 'react-dom/server';\nimport { PageView } from '../../internal/${spec.slug}/view';\nit('uses the shared frame and translated title',()=>{for (const locale of ['en','ar'] as const) {const html = renderToStaticMarkup(<PageView locale={locale}/>);expect(html).toContain('class="bt-page"');expect(html.match(/<h1\\b/g)).toHaveLength(1);expect(html).toContain(renderToStaticMarkup(<>{locale === 'ar' ? ${quoted(spec.ar)} : ${quoted(spec.en)}}</>));}});\n`,
  }};
}
function ownedDestination(root,file) {
  const target = resolve(root,file), base = realpathSync(root), path = relative(base,target);
  if (path === '..' || path.startsWith('../') || isAbsolute(path)) throw new Error('Page destination escapes this checkout');
  let parent = target;while (!existsSync(parent)) parent = dirname(parent);
  const existing = relative(base,realpathSync(parent));
  if (existing === '..' || existing.startsWith('../') || isAbsolute(existing)) throw new Error('Page destination resolves outside this checkout');
}
export function createStartingPage(root,spec) {
  const proposal = startingFiles(spec);for (const file of [PAGE_TABLE,PAGE_TABLE+'.lock',PAGE_TABLE+'.new',...Object.keys(proposal.files)]) ownedDestination(root,file);
  const original = readFileSync(join(root,PAGE_TABLE),'utf8'), table = JSON.parse(original), next = [...table,proposal.entry];
  const errors = validatePageTable(next);if (errors.length) throw new Error(errors.join('; '));
  for (const file of Object.keys(proposal.files)) if (existsSync(join(root,file))) throw new Error(`Refusing to replace ${file}`);
  const created = [], lockFile = join(root,PAGE_TABLE+'.lock'), temporary = join(root,PAGE_TABLE+'.new');
  const lock = openSync(lockFile,'wx');let ownsTemporary = false;
  try {if (readFileSync(join(root,PAGE_TABLE),'utf8') !== original) throw new Error('Page table changed; retry');for (const [file,source] of Object.entries(proposal.files)) {mkdirSync(dirname(join(root,file)),{recursive:true});const descriptor = openSync(join(root,file),'wx');created.push(file);try {writeFileSync(descriptor,source);} finally {closeSync(descriptor);}}
    if (readFileSync(join(root,PAGE_TABLE),'utf8') !== original) throw new Error('Page table changed; retry');
    const descriptor = openSync(temporary,'wx');ownsTemporary = true;try {writeFileSync(descriptor,JSON.stringify(next,null,2)+'\n');} finally {closeSync(descriptor);}renameSync(temporary,join(root,PAGE_TABLE));
  } catch (error) {for (const file of created) unlinkSync(join(root,file));throw error;}
  finally {closeSync(lock);unlinkSync(lockFile);if (ownsTemporary && existsSync(temporary)) unlinkSync(temporary);}
  return proposal.entry;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {const args = process.argv.slice(2);if (args[0] === '--') args.shift();const [slug,en,ar,bodyEn,bodyAr,reason,...extra] = args;if (extra.length) throw new Error('Unexpected arguments');console.log(createStartingPage(ROOT,{slug,en,ar,bodyEn,bodyAr,reason}).route);} catch (error) {console.error(error.message);process.exitCode = 1;}
}
