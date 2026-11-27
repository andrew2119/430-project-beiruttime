// Run the foundation browser matrix at desktop and phone sizes in headless Chrome, then take
// and check the eight locale and theme screenshots.
// Usage: node .github/ci/browser.mjs <report.json>
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
  try {
    await new AsyncFunction('page', 'console', source)(matrixPage(session), output);
  } finally {
    await session.close();
  }
  for (const line of lines.slice(0, -1)) console.log(line);
  const checks = JSON.parse(lines.at(-1));
  if (!Array.isArray(checks) || checks.length !== 12) throw new Error(`${size}: expected 12 checks, got ${checks?.length}`);
  return checks.length;
}

async function screenshot(size, locale, theme, folder) {
  const cell = {...sizes[size], locale, theme};
  const session = await browser({browserPath, origin, cell});
  try {
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
  } finally {
    await session.close();
  }
}

const report = process.argv[2];
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
for (const size of Object.keys(sizes)) await step(`matrix ${size}`, () => matrix(size));
const folder = await mkdtemp(join(process.env.RUNNER_TEMP || tmpdir(), 'bt-shots-'));
for (const size of Object.keys(sizes)) {
  for (const locale of ['en', 'ar']) {
    for (const theme of ['light', 'dark']) await step(`screenshot ${size} ${locale} ${theme}`, () => screenshot(size, locale, theme, folder));
  }
}
const ok = problems.length === 0 && passed.length === 10;
await writeFile(report, JSON.stringify({suite: 'browser', ok, problems, checks: passed}) + '\n');
process.exit(ok ? 0 : 1);
