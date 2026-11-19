import definitions from '@/lib/page-speed/pages.json';
import publicPages from './pages.json';

/** Compose before the shared registry snapshots its entries. Its path dependency
 * initializes this module for both direct registry reads and lazy shell mounting.
 * Only static owned pages join here; no command or private read is introduced. */
for (const page of publicPages) {
  const existing = definitions.find(entry => entry.route === page.route);
  if (existing) {
    if (JSON.stringify(existing) !== JSON.stringify(page)) throw new Error('Conflicting page contract');
  } else definitions.push(page);
}
