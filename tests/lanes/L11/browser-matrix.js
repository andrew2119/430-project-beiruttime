// Feed to CHROME_DEVTOOLS_AXI_SESSION=bt-l11 chrome-devtools-axi run.
// Set the viewport with emulate first: 1440x1000x1 or 390x844x1,mobile,touch.
const results=[];
for(const locale of ['en','ar']){
  await page.open(`http://127.0.0.1:3111/${locale}/services`);
  await page.wait('.directory-business button');
  await page.click('.directory-business button');
  await page.wait('.movement-panel input');
  for(const theme of ['light','dark']){
    if(await page.eval(()=>document.documentElement.dataset.theme)!==theme) await page.click('.preferences button');
    await page.click('.directory-business button');
    await page.wait(80);
    const context=JSON.parse(await page.eval(()=>JSON.stringify({
      width:innerWidth,height:innerHeight,locale:document.documentElement.lang,dir:document.documentElement.dir,
      theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth,
      businessCount:document.querySelectorAll('.directory-business').length,
      sampleLabels:document.querySelectorAll('.directory-demo').length,
      detailFocused:document.activeElement.classList.contains('directory-detail'),
      publicContextPreserved:new URL(location.href).searchParams.get('business')==='00000000-0011-4000-8000-000000000001'&&document.querySelector('.locale-control').href.includes('business='),
      smallControls:[...document.querySelectorAll('.directory-page button,.directory-page .button,.directory-page input,.directory-page select')].filter(e=>e.getBoundingClientRect().height<43.5).length,
      foreground:getComputedStyle(document.body).color,background:getComputedStyle(document.body).backgroundColor
    })));
    if(context.locale!==locale||context.dir!==(locale==='ar'?'rtl':'ltr')||context.theme!==theme||context.overflow||context.businessCount!==1||context.sampleLabels<2||!context.detailFocused||!context.publicContextPreserved||context.smallControls)throw new Error(JSON.stringify(context));
    // CSS fill changes the DOM without notifying React; use focused keyboard input.
    await page.eval(()=>{const input=document.querySelector('.movement-panel form > label:last-of-type > input');input.focus();input.select();});
    await page.type('hours, minutes, seconds, chronograph');
    const value=await page.eval(()=>document.querySelector('.movement-panel form > label:last-of-type > input').value);
    if(value!=='hours, minutes, seconds, chronograph')throw new Error(`Functions editing mismatch: ${value}`);
    await page.eval(()=>document.querySelector('.movement-panel a.button').scrollIntoView({block:'center',behavior:'instant'}));
    const target=JSON.parse(await page.eval(()=>{const e=document.querySelector('.movement-panel a.button'),r=e.getBoundingClientRect(),m=document.querySelector('main').getBoundingClientRect();return JSON.stringify({reachable:r.top>=m.top&&r.bottom<=m.bottom,uncovered:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),signIn:e.getAttribute('href').includes('/account?next=')});}));
    if(!target.reachable||!target.uncovered||!target.signIn)throw new Error(JSON.stringify(target));
    results.push({...context,...target});
  }
}
console.log(JSON.stringify(results));
