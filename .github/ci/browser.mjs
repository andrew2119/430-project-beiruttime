// Run the foundation browser matrix at desktop and phone sizes in headless Chrome, then take
// and check the four locale and theme screenshots of each size.
// Usage: node .github/ci/browser.mjs <report.json> [desktop|phone]
// With a size it runs only that size's five checks; without one it runs all ten.
import {readFile, writeFile, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {browser} from '../../tests/native/n09/features/ctx.mjs';
import {validateScreenshot} from '../../scripts/native-browser.mjs';

const root = resolve(fileURLToPath(import.meta.url), '../../..');
const origin = 'http://localhost:3000';
const browserPath = process.env.BT_BROWSER || '/opt/google/chrome/chrome';
const sizes = {
  desktop: {width: 1440, height: 900, dpr: 1, mobile: false, touch: false},
  phone: {width: 390, height: 844, dpr: 3, mobile: true, touch: true},
};
const pause = ms => new Promise(done => setTimeout(done, ms));
const AsyncFunction = (async () => {}).constructor;

// Close the session after the work. When the work and the close both fail, report both: the
// close error alone would hide why the check failed.
async function withSession(session, work) {
  let failure = null;
  try {
    return await work();
  } catch (error) {
    failure = error;
    throw error;
  } finally {
    try {
      await session.close();
    } catch (error) {
      if (failure === null) throw error;
      throw new Error(`${failure?.message ?? failure}; closing the session also failed: ${error?.message ?? error}`);
    }
  }
}

// The matrix script drives a small page interface; this maps it onto the prepared session.
function matrixPage(session) {
  const evaluate = what => session.page.evaluate(typeof what === 'string' ? `() => (${what})` : what);
  return {
    async open(url) {
      await session.page.goto(url);
      const status = await session.page.evaluate(() => performance.getEntriesByType('navigation').pop()?.responseStatus);
      return {url: await session.page.url(), status};
    },
    eval: evaluate,
    async wait(what) {
      if (typeof what === 'number') return pause(what);
      return session.page.waitFor(what, {timeout: 30000});
    },
    click: selector => session.page.click(selector),
    press: key => session.page.press(key),
  };
}

async function matrix(size) {
  const source = await readFile(join(root, 'tests/foundation/browser-matrix.js'), 'utf8');
  const session = await browser({browserPath, origin, cell: {...sizes[size], locale: 'en', theme: 'light'}});
  const lines = [];
  const output = {log: line => lines.push(String(line))};
  await withSession(session, () => new AsyncFunction('page', 'console', source)(matrixPage(session), output));
  for (const line of lines.slice(0, -1)) console.log(line);
  const checks = JSON.parse(lines.at(-1));
  if (!Array.isArray(checks) || checks.length !== 12) throw new Error(`${size}: expected 12 checks, got ${checks?.length}`);
  return checks.length;
}

async function screenshot(size, locale, theme, folder) {
  const cell = {...sizes[size], locale, theme};
  const session = await browser({browserPath, origin, cell});
  await withSession(session, async () => {
    await session.page.goto(`/${locale}`);
    await session.page.waitFor('#main-content .bt-page h1', {timeout: 30000});
    const state = await session.page.evaluate(() => ({
      lang: document.documentElement.lang, theme: document.documentElement.dataset.theme,
      width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
    }));
    if (state.lang !== locale || state.theme !== theme || state.width !== cell.width || state.dpr !== cell.dpr) {
      throw new Error(`${size} ${locale} ${theme}: page state ${JSON.stringify(state)}`);
    }
    const path = join(folder, `${size}-${locale}-${theme}.png`);
    await session.screenshot(path);
    await validateScreenshot(path, cell);
  });
}

const report = process.argv[2];
const chosen = process.argv[3] ? [process.argv[3]] : Object.keys(sizes);
if (!chosen.every(size => size in sizes)) throw new Error(`unknown size ${process.argv[3]}`);
const problems = [];
const passed = [];
async function step(name, action) {
  try {
    await action();
    passed.push(name);
    console.log(`PASS ${name}`);
  } catch (error) {
    problems.push(`${name}: ${error.message}`);
    console.log(`FAIL ${name}: ${error.message}`);
  }
}
const folder = await mkdtemp(join(process.env.RUNNER_TEMP || tmpdir(), 'bt-shots-'));
for (const size of chosen) {
  await step(`matrix ${size}`, () => matrix(size));
  for (const locale of ['en', 'ar']) {
    for (const theme of ['light', 'dark']) await step(`screenshot ${size} ${locale} ${theme}`, () => screenshot(size, locale, theme, folder));
  }
}
const ok = problems.length === 0 && passed.length === 5 * chosen.length;
await writeFile(report, JSON.stringify({suite: 'browser', ok, problems, checks: passed}) + '\n');
process.exit(ok ? 0 : 1);
