// Run twice after browser-save.js: desktop, then actual 390px mobile emulation.
const current = await page.eval(() => ({origin:location.origin,id:new URL(location.href).searchParams.get('draft'),width:innerWidth}));
if (!current.id || ![390,1280].includes(current.width)) throw Error('Saved draft and explicit proof viewport required');
const cases=[];
for (const language of ['en','ar']) for (const theme of ['light','dark']) {
  await page.open(`${current.origin}/${language}/custom-requests?draft=${encodeURIComponent(current.id)}`);
  await page.wait('textarea[name=notes]');
  if (await page.eval(() => document.documentElement.dataset.theme) !== theme) {
    const match=/uid=(\S+) button "(?:Switch to (?:dark|light) theme|التبديل إلى المظهر (?:الداكن|الفاتح))"/.exec(await page.snapshot());
    if (!match) throw Error('Theme control missing');
    await page.click('@'+match[1]);
  }
  await page.wait(200);
  const result=await page.eval(() => ({language:document.documentElement.lang,theme:document.documentElement.dataset.theme,
    direction:document.documentElement.dir,width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
    notesPersisted:document.querySelector('textarea[name=notes]')?.value==='Sample bilingual current notes',
    fieldPixels:parseFloat(getComputedStyle(document.querySelector('textarea[name=notes]')).fontSize),
    targets:[...document.querySelectorAll('main button,main input,main select,main textarea,main a.button')].filter(element=>!element.disabled).every(element=>element.getBoundingClientRect().height>=43.9),
    background:getComputedStyle(document.body).backgroundColor}));
  if(result.width!==current.width||result.language!==language||result.theme!==theme||result.direction!==(language==='ar'?'rtl':'ltr')||result.overflow||!result.notesPersisted||!result.targets||(current.width===390&&result.fieldPixels<16)) throw Error('Private draft matrix failed');
  await page.press('Tab');
  const focus=await page.eval(()=>document.activeElement!==document.body);
  if(!focus)throw Error('Keyboard focus missing');
  cases.push({...result,keyboardFocus:true});
}
if(new Set(cases.map(row=>row.background)).size!==2)throw Error('Theme did not change the rendered palette');
console.log(JSON.stringify({realIdentity:true,fullSliceAccepted:false,cases}));
