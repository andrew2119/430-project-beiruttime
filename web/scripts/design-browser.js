// Read/preferences-only shell regression. Run in an isolated chrome-devtools-axi
// session after `emulate --viewport 390x844x3,mobile,touch`; point origin at your
// own loopback web server. This does not create accounts or submit transactions.
const origin = 'http://127.0.0.1:3247';
const results = [];
const check = async (name, run) => {
  try { results.push({ name, passed: true, ...await run() }); }
  catch (error) { results.push({ name, passed: false, error: String(error) }); }
};
for (const locale of ['en', 'ar']) {
  await page.open(`${origin}/${locale}`);
  await page.wait('.pg-dept-card');
  await check(`${locale}: source home cards translate to one phone column`, async () => {
    const state = await page.eval(() => ({ viewport: innerWidth, columns: getComputedStyle(document.querySelector('.pg-dept-grid')).gridTemplateColumns, copyWidth: document.querySelector('.pg-dept-card-copy').getBoundingClientRect().width }));
    if (state.viewport !== 390 || state.columns.split(' ').length !== 1 || state.copyWidth < 160) throw Error(JSON.stringify(state));
    return state;
  });
  await page.open(`${origin}/${locale}/settings`);
  await page.wait('#settings-language');
  for (const door of ['.pg-mobile-menu', '.psb-dock-menu']) {
    await check(`${locale}: ${door} Escape restores invoker`, async () => {
      await page.click(door);
      await page.wait('#phone-menu[data-state="open"]');
      await page.wait(350);
      const drawer = await page.eval(() => {
        const e = document.querySelector('#phone-menu'), r = e.getBoundingClientRect();
        return { viewport: innerWidth, x: r.x, right: r.right, dir: getComputedStyle(e).direction, role: e.getAttribute('role') };
      });
      await page.press('Escape');
      await page.wait(350);
      const restored = await page.eval(`() => document.activeElement.matches(${JSON.stringify(door)})`);
      if (!restored || drawer.viewport !== 390 || drawer.dir !== (locale === 'ar' ? 'rtl' : 'ltr') || drawer.role !== 'dialog') throw Error(JSON.stringify({ drawer, restored }));
      if (locale === 'ar' ? Math.abs(drawer.right - 380) > 1 : Math.abs(drawer.x - 10) > 1) throw Error('Drawer edge not mirrored');
      return { drawer, restored };
    });
  }
  await check(`${locale}: drawer navigation hands focus to destination`, async () => {
    await page.click('.psb-dock-menu');
    await page.wait('#phone-menu[data-state="open"]');
    await page.click(`#phone-menu a[href="/${locale}/account"]`);
    await page.wait('main h1');
    await page.wait(400);
    const state = await page.eval(() => ({ path: location.pathname, open: !!document.querySelector('#phone-menu[data-state="open"]'), focused: document.activeElement.id }));
    if (state.path !== `/${locale}/account` || state.open || state.focused !== 'main-content') throw Error(JSON.stringify(state));
    return state;
  });
  await page.open(`${origin}/${locale}/settings`);
  await page.wait('#settings-appearance');
  await check(`${locale}: theme-radio keyboard commits selection and focus`, async () => {
    const before = await page.eval(() => document.documentElement.dataset.theme);
    await page.eval(() => document.querySelector('[role="radio"][aria-checked="true"]').focus());
    await page.press('ArrowRight');
    await page.wait(700);
    const state = await page.eval(() => ({ theme: document.documentElement.dataset.theme, focusChecked: document.activeElement.getAttribute('aria-checked'), cookie: document.cookie }));
    if (state.theme === before || state.focusChecked !== 'true' || !state.cookie.includes(`bt-theme=${state.theme}`)) throw Error(JSON.stringify(state));
    await page.open(`${origin}/${locale}/settings`);
    await page.wait('#settings-appearance');
    if (await page.eval(() => document.documentElement.dataset.theme) !== state.theme) throw Error('Theme not retained');
    return state;
  });
  await check(`${locale}: language changes route, direction and preference`, async () => {
    const next = locale === 'en' ? 'ar' : 'en';
    await page.click(`#settings-language button:has(span[lang="${next}"])`);
    await page.wait(700);
    const state = await page.eval(() => ({ path: location.pathname, lang: document.documentElement.lang, dir: document.documentElement.dir, cookie: document.cookie }));
    if (state.path !== `/${next}/settings` || state.lang !== next || state.dir !== (next === 'ar' ? 'rtl' : 'ltr') || !state.cookie.includes(`bt-locale=${next}`)) throw Error(JSON.stringify(state));
    return state;
  });
}
// Keep diagnostic rows even on failure; the caller must assert `passed`.
console.log(JSON.stringify({ passed: results.every(row => row.passed), results }, null, 2));
