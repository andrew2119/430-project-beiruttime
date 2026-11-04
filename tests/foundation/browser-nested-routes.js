// Run only against the isolated FOUNDATION_PROXY_PROOF production image.
const origin = PROOF_ORIGIN;
const checks = [];
const expectedWidth = PROOF_WIDTH;
const routes = PROOF_ROUTES;
const fixture = PROOF_FIXTURE;
for (const locale of ['en', 'ar']) for (const theme of ['light', 'dark']) {
  await page.eval(`document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`);
  for (const route of routes) {
    const result = await page.open(`${origin}/${locale}${route}?view=open`);
    if (result.status !== 200) throw new Error(`Unexpected nested-route status: ${result.status}`);
    await page.wait('main');
    const check = await page.eval(() => {
      const root = document.documentElement, proof = document.querySelector('[data-proxy-proof]');
      return { path: location.pathname, search: location.search, locale: root.lang, dir: root.dir,
        theme: root.dataset.theme, registered: proof?.dataset.registered, internalPath: proof?.dataset.path,
        forwardedLocale: proof?.dataset.locale, width: innerWidth, height: innerHeight,
        overflow: document.documentElement.scrollWidth > innerWidth || document.body.scrollWidth > innerWidth };
    });
    if (check.path !== `/${locale}${route}` || check.search !== '?view=open' || check.locale !== locale ||
        check.dir !== (locale === 'ar' ? 'rtl' : 'ltr') || check.theme !== theme ||
        (fixture && (check.forwardedLocale !== locale || check.registered !== 'true' || check.internalPath !== route)) || check.width !== expectedWidth || check.overflow) {
      throw new Error(JSON.stringify(check));
    }
    checks.push(check);
  }
}
console.log(JSON.stringify(checks, null, 2));
