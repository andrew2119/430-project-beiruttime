// Browser checks against the production image.
const checks = [];
const origin = 'http://localhost:3000';
const menuTrigger = '.bt-shell-topbar button[aria-haspopup="dialog"]';
const openMenu = '.bt-navigation-sheet[role="dialog"][data-state="open"]';

async function waitFor(read, accepts, message) {
  let actual;
  for (let attempt = 0; attempt < 100; attempt++) {
    actual = await page.eval(read);
    if (accepts(actual)) return actual;
    await page.wait(50);
  }
  throw new Error(message + ': ' + JSON.stringify(actual));
}

async function waitForFrame() {
  await page.wait('#main-content .bt-page h1');
  await waitFor(() => innerWidth <= 850
    ? !document.querySelector('.bt-shell-rail') && !!document.querySelector('.bt-shell-topbar button[aria-haspopup="dialog"]')
    : !!document.querySelector('.bt-shell-rail .bt-shell-navigation'), Boolean, 'Navigation did not settle');
  await page.eval(async () => { await document.fonts.ready; return true; });
}

async function measureFrame() {
  return page.eval(() => {
    const root = document.documentElement, shell = document.querySelector('.bt-shell');
    const main = document.querySelector('#main-content.bt-shell-content');
    const phone = innerWidth <= 850;
    const topbar = document.querySelector('.bt-shell-topbar'), rail = document.querySelector('.bt-shell-rail');
    const navigation = phone ? topbar : rail;
    if (!shell || !main || !navigation || !topbar) throw new Error('Foundation frame is missing');
    const rect = main.getBoundingClientRect(), nav = navigation.getBoundingClientRect();
    const visible = node => {
      if (!node) return false;
      const box = node.getBoundingClientRect(), style = getComputedStyle(node);
      return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && !node.closest('[inert]');
    };
    return {
      path: location.pathname, width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
      locale: root.lang, dir: root.dir, shellLocale: shell.lang, shellDir: shell.dir, theme: root.dataset.theme,
      heading: main.querySelector('h1')?.textContent.trim(), mainCount: document.querySelectorAll('main').length, phone,
      overflow: [root, document.body, shell, main, navigation].some(node => node.scrollWidth > node.clientWidth),
      navVisible: visible(navigation) && !!navigation.querySelector(phone ? 'button[aria-haspopup="dialog"]' : '.bt-shell-navigation'),
      responsive: phone ? visible(topbar) && !visible(rail) : !visible(topbar) && visible(rail),
      separated: phone ? nav.bottom <= rect.top : nav.right <= rect.left || rect.right <= nav.left,
      withinViewport: rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1,
      preferencesVisible: !!navigation.querySelector('.bt-locale-control') && (phone || !!navigation.querySelector('.bt-theme-switch')),
      targetSizes: [...navigation.querySelectorAll('a,button'), ...main.querySelectorAll('a,button')].filter(visible).map(node => {
        const box = node.getBoundingClientRect();
        return { label: node.getAttribute('aria-label') || node.textContent.trim(), w: box.width, h: box.height };
      }),
    };
  });
}

async function reportOverflow(check) {
  if (!check.overflow) return;
  check.overflowElements = await page.eval(() => {
    const offenders = [];
    for (const node of document.querySelectorAll('*')) {
      const box = node.getBoundingClientRect(), style = getComputedStyle(node);
      if (!box.width || !box.height || style.display === 'none' || style.visibility === 'hidden' || node.closest('[inert]')) continue;
      const frame = node.closest('.bt-shell-content,.bt-shell-rail,.bt-navigation-sheet');
      const bounds = frame?.getBoundingClientRect() ?? { left: 0, right: innerWidth };
      const identity = { tag: node.tagName.toLowerCase(), classes: node.getAttribute('class') || '' };
      if (node.scrollWidth > node.clientWidth || box.left < bounds.left - 1 || box.right > bounds.right + 1) {
        offenders.push({ ...identity, width: box.width, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, left: box.left, right: box.right });
      }
      // Sticky header paint can overflow without any element's own box growing.
      for (const pseudo of ['::before', '::after']) {
        const paint = getComputedStyle(node, pseudo), width = parseFloat(paint.width);
        if (paint.content && !['none', 'normal'].includes(paint.content) && paint.display !== 'none' && paint.visibility !== 'hidden' && paint.opacity !== '0' && width > box.width + 1) {
          offenders.push({ ...identity, pseudo, width, hostWidth: box.width, insetInlineStart: paint.insetInlineStart, insetInlineEnd: paint.insetInlineEnd });
        }
      }
    }
    return offenders.sort((a, b) => Math.max(b.width, b.scrollWidth || 0) - Math.max(a.width, a.scrollWidth || 0)).slice(0, 15);
  });
  console.log('Horizontal overflow: ' + JSON.stringify(check));
}

async function waitForMenuFocus() {
  await waitFor(() => {
    const dialog = document.querySelector('.bt-navigation-sheet[role="dialog"][data-state="open"]');
    return !!dialog && dialog.contains(document.activeElement) &&
      dialog.getAnimations().every(animation => !animation.pending && animation.playState !== 'running');
  }, Boolean, 'Navigation dialog did not settle with focus');
}

async function checkNavigation(locale, theme, phone) {
  if (phone) {
    await page.click(menuTrigger);
    await waitForMenuFocus();
    const dialog = await page.eval(() => {
      const panel = document.querySelector('.bt-navigation-sheet[role="dialog"][data-state="open"]');
      return {
        dir: getComputedStyle(panel).direction,
        overflow: [document.documentElement, document.body, panel, ...panel.querySelectorAll('.bt-surface-body')]
          .some(node => node.scrollWidth > node.clientWidth),
        preferences: !!panel.querySelector('.bt-locale-control') && !!panel.querySelector('.bt-theme-switch'),
        targetSizes: [...panel.querySelectorAll('a,button')].map(node => {
          const box = node.getBoundingClientRect();
          return { label: node.getAttribute('aria-label') || node.textContent.trim(), w: box.width, h: box.height };
        }).filter(box => box.w > 0 && box.h > 0),
      };
    });
    await reportOverflow(dialog);
    if (dialog.dir !== (locale === 'ar' ? 'rtl' : 'ltr') || dialog.overflow || !dialog.preferences ||
        !dialog.targetSizes.length || dialog.targetSizes.some(box => box.w < 44 || box.h < 44)) {
      throw new Error('Navigation dialog geometry: ' + JSON.stringify(dialog));
    }
    await page.press('Escape');
    await waitFor(() => {
      const trigger = document.querySelector('.bt-shell-topbar button[aria-haspopup="dialog"]');
      return !document.querySelector('.bt-navigation-sheet') && document.activeElement === trigger && trigger?.getAttribute('aria-expanded') === 'false';
    }, Boolean, 'Escape did not restore menu trigger focus');
    await page.click(menuTrigger);
    await waitForMenuFocus();
  }
  // A marker on the window survives an in-app move but not a whole new page load.
  await page.eval(() => { window.btMatrixSameDocument = true; return true; });
  await page.click(`${phone ? openMenu : '.bt-shell-rail'} .bt-shell-navigation a[href="/${locale}/about"]`);
  const arrived = await waitFor(() => ({
    path: location.pathname, closed: !document.querySelector('.bt-navigation-sheet'), sameDocument: window.btMatrixSameDocument === true,
  }), state => state.path === `/${locale}/about` && state.closed, 'Navigation did not reach the about page');
  if (!arrived.sameDocument) throw new Error('Navigation link loaded a whole new page: ' + JSON.stringify(arrived));
  await waitFor(() => {
    const active = document.activeElement;
    const classes = typeof active?.className === 'string' ? active.className.trim().split(/\s+/).filter(Boolean) : [];
    return { focus: active?.id, active: active ? [active.tagName.toLowerCase(), ...classes].join('.') : null };
  }, state => state.focus === 'main-content', 'Route focus was not handed to main');

  const other = locale === 'en' ? 'ar' : 'en';
  await page.click(`${phone ? '.bt-shell-topbar' : '.bt-shell-rail'} .bt-locale-control`);
  await waitFor(() => ({
    path: location.pathname, locale: document.documentElement.lang, dir: document.documentElement.dir,
    shellLocale: document.querySelector('.bt-shell')?.lang, shellDir: document.querySelector('.bt-shell')?.dir,
    theme: document.documentElement.dataset.theme,
  }), state => state.path === `/${other}/about` && state.locale === other && state.shellLocale === other &&
    state.dir === (other === 'ar' ? 'rtl' : 'ltr') && state.shellDir === state.dir && state.theme === theme,
  'Locale switch lost the route, direction or theme');
  checks.push({ locale, theme, phone, navigation: phone ? 'dialog focus, Escape and destination focus passed' : 'destination focus passed', localeSwitch: 'route, direction and theme preserved' });
}

// Establish the origin before setting preference cookies, and reject a clamped viewport.
const initial = await page.open(`${origin}/en`);
if (initial.status !== 200) throw new Error('Unexpected initial page status: ' + initial.status);
await waitForFrame();
const expectedWidth = await page.eval(() => innerWidth);
if (![390, 1440].includes(expectedWidth)) throw new Error('Expected a 390 or 1440 pixel viewport, got ' + expectedWidth);

for (const locale of ['en', 'ar']) for (const theme of ['light', 'dark']) {
  await page.eval(`document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`);
  for (const route of ['', '/about']) {
    const result = await page.open(`${origin}/${locale}${route}`);
    if (result.status !== 200) throw new Error(`Unexpected page status ${locale}/${theme}/${route}: ${result.status}`);
    await waitForFrame();
    if (!route) await page.wait('#main-content .bt-home-link');
    const check = await measureFrame();
    await reportOverflow(check);
    if (check.path !== `/${locale}${route}` || check.width !== expectedWidth || check.locale !== locale || check.shellLocale !== locale ||
        check.theme !== theme || check.dir !== (locale === 'ar' ? 'rtl' : 'ltr') || check.shellDir !== check.dir || check.overflow || !check.heading || check.mainCount !== 1) {
      throw new Error(JSON.stringify(check));
    }
    if (!check.navVisible || !check.responsive || !check.separated || !check.withinViewport || !check.preferencesVisible || !check.targetSizes.length || check.targetSizes.some(box => box.w < 44 || box.h < 44)) {
      throw new Error('Shell geometry: ' + JSON.stringify(check));
    }
    checks.push(check);
    if (!route) await checkNavigation(locale, theme, check.phone);
  }
}
console.log(JSON.stringify(checks, null, 2));
