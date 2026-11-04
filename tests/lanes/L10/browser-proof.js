// Run via: CHROME_DEVTOOLS_AXI_SESSION=bt-l10b chrome-devtools-axi run < tests/lanes/L10/browser-proof.js
// The caller selects desktop or exact phone emulation before running this script.
const base = 'http://localhost:3110';
const query = '?brand=20000000-0000-4000-8000-000000000001&base=atelier-38&caliber=manual-01';
for (const locale of ['en', 'ar']) {
  await page.open(`${base}/${locale}/customize${query}`);
  await page.wait('.bo-option');
  for (const theme of ['light', 'dark']) {
    if (await page.eval(() => document.documentElement.dataset.theme) !== theme) await page.click('.preferences button');
    for (let category = 1; category <= 4; category++) {
      await page.click(`.bo-categories button:nth-child(${category})`);
      await page.wait('.bo-option');
      await page.click('.bo-option input');
      const result = await page.eval(() => ({
        locale: document.documentElement.lang,
        direction: document.documentElement.dir,
        theme: document.documentElement.dataset.theme,
        width: innerWidth,
        dpr: devicePixelRatio,
        overflow: [...document.querySelectorAll('.bo-page,.bo-binding,.bo-options,.bo-summary')].some(node => node.scrollWidth > node.clientWidth + 1),
        controlsReachable: [...document.querySelectorAll('.bo-binding select')].every(node => node.getBoundingClientRect().height >= 44),
        phoneInputFloor: innerWidth > 850 || [...document.querySelectorAll('.bo-binding select')].every(node => parseFloat(getComputedStyle(node).fontSize) >= 16),
        selected: !!document.querySelector('.bo-option input:checked'),
        signedOutSaveDisabled: document.querySelector('.bo-actions button').disabled,
        sampleNotice: !!document.querySelector('.bo-workbench > .notice'),
        optionText: document.querySelector('.bo-option h2').textContent,
      }));
      if (![390,1440].includes(result.width) || (result.width===390&&result.dpr!==3) || result.locale !== locale || result.direction !== (locale === 'ar' ? 'rtl' : 'ltr') || result.theme !== theme || result.overflow || !result.controlsReachable || !result.phoneInputFloor || !result.selected || !result.signedOutSaveDisabled || !result.sampleNotice) throw new Error(JSON.stringify(result));
      console.log(JSON.stringify({category, ...result}));
    }
  }
}
