// Linux transport for the existing L12 browser matrix and separate refresh lineage.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {localBrowser} from '../../native/n09/features/ctx.mjs';

const [mode, out] = process.argv.slice(2);
const origin = 'http://127.0.0.1:3412';
const browserPath = process.env.BT_L12_CHROME;
const AsyncFunction = (async () => {}).constructor;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const context = JSON.parse(await readFile('/dev/stdin', 'utf8'));
const script = await readFile(new URL('./connected-browser.js', import.meta.url), 'utf8');
assert(['matrix', 'screens'].includes(mode));

async function withBrowser(width, work) {
  const mobile = width === 390;
  const session = await localBrowser({browserPath, origin, profileRoot: out, loopbackOnly: true,
    cell: {locale: 'en', theme: 'light', width, mobile, touch: mobile,
      height: mode === 'matrix' ? 844 : 1000, dpr: mode === 'matrix' ? 3 : 1}});
  try { await work(session); }
  finally { await session.close(); }
}

async function matrix(width) {
  await withBrowser(width, async ({page}) => {
    const adapter = {
      open: path => page.goto(path),
      eval: expression => page.evaluate(typeof expression === 'string' ? `() => (${expression})` : expression),
      wait: value => typeof value === 'number' ? pause(value) : page.waitFor(value, {timeout: 30000}),
      fill: page.fill, click: page.click, press: page.press,
    };
    const logs = [];
    await new AsyncFunction('page', 'CONTEXT', 'console', script)(adapter, {...context, origin, width},
      {log: line => logs.push(line)});
    const checks = JSON.parse(logs.at(-1));
    const expected = ['seller','buyer-fixed-policy'].flatMap(role => ['en','ar'].flatMap(locale =>
      ['light','dark'].map(theme => `${role}/${locale}/${theme}`)));
    assert.deepEqual(checks.map(c => `${c.role}/${c.locale}/${c.theme}`), expected);
    await writeFile(join(out, `browser-${width}.json`), JSON.stringify(checks), {flag: 'wx', mode: 0o600});
  });
}

async function screenshots() {
  // Use one real login cookie exactly once across all eight captures, not one per cell.
  assert(context.refresh);
  await withBrowser(1280, async session => {
    const {call, page} = session;
    assert((await call('Network.setCookie', {name: 'bt_refresh', value: context.refresh, url: origin,
      path: '/', httpOnly: true, sameSite: 'Strict'})).success);
    for (const width of [1280, 390]) {
      await call('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: width === 390});
      for (const locale of ['en','ar']) for (const theme of ['light','dark']) {
        assert((await call('Network.setCookie', {name: 'bt-theme', value: theme, url: origin, path: '/'})).success);
        await page.goto(`/${locale}/auction-policy?listing_id=${encodeURIComponent(context.listing)}`);
        let facts;
        for (let attempt = 0; attempt < 150; attempt++) {
          facts = await page.evaluate(() => ({
            loaded: !!document.querySelector('.auction-policy-panel dd'),
            purchase: !!document.querySelector('.auction-policy-form, a[href*="/checkout?order_id="]'),
            width: innerWidth, theme: document.documentElement.dataset.theme, locale: document.documentElement.lang,
            overflow: document.documentElement.scrollWidth > innerWidth + 1,
          }));
          if (facts.loaded && facts.theme === theme && facts.locale === locale) break;
          await pause(200);
        }
        assert(facts.loaded && facts.theme === theme && facts.locale === locale && facts.width === width
          && !facts.overflow && !facts.purchase);
        await pause(500);
        await session.screenshot(join(out, `fixed-policy-${locale}-${theme}-${width}.png`));
      }
    }
  });
}

try {
  if (mode === 'matrix') {
    for (const width of [1280, 390]) await matrix(width);
  } else await screenshots();
} catch {
  // A browser exception may contain authenticated page text. Keep it out of public logs.
  console.error(`L12 ${mode} failed`);
  process.exitCode = 1;
}
