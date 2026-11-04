// Run after registering a buyer through L01's actual account form against live_server.py.
// No access token, cookie or simulated principal is injected by this proof.
let currentUrl=await page.eval(()=>location.href);
const viewport=await page.eval(()=>innerWidth===390?'phone':'desktop');
  for(const locale of ['en','ar']) {
    currentUrl=currentUrl.replace(/\/(en|ar)\/customize/,`/${locale}/customize`);
    await page.open(currentUrl);
    await page.wait('.bo-option');
    await page.wait(500);
    for(const theme of ['light','dark']) {
      if(await page.eval(()=>document.documentElement.dataset.theme)!==theme) await page.click('.preferences button');
      for(let category=1;category<=4;category++) {
        await page.click(`.bo-categories button:nth-child(${category})`);
        await page.wait('.bo-option');
        await page.click('.bo-option input');
        const before=await page.eval(()=>Number(document.querySelector('.bo-summary section bdi')?.textContent??0));
        await page.click('.bo-actions button');
        await page.wait(300);
        const result=await page.eval(()=>({
          locale:document.documentElement.lang,direction:document.documentElement.dir,
          theme:document.documentElement.dataset.theme,width:innerWidth,dpr:devicePixelRatio,
          revision:Number(document.querySelector('.bo-summary section bdi')?.textContent??0),
          selections:document.querySelectorAll('.bo-saved>div').length,
          overflow:document.documentElement.scrollWidth>innerWidth+1,
          controls:[...document.querySelectorAll('.bo-binding select')].every(node=>node.getBoundingClientRect().height>=44),
          inputFloor:innerWidth>850||[...document.querySelectorAll('.bo-binding select')].every(node=>parseFloat(getComputedStyle(node).fontSize)>=16),
          selected:!!document.querySelector('.bo-option input:checked'),
          errors:[...document.querySelectorAll('[role="alert"]')].map(node=>node.textContent).filter(Boolean),
          sample:!!document.querySelector('.bo-workbench>.notice'),
          url:location.href,
        }));
        if(result.revision!==before+1||result.locale!==locale||result.theme!==theme||result.direction!==(locale==='ar'?'rtl':'ltr')||
          result.width!==(viewport==='phone'?390:1440)||(viewport==='phone'&&result.dpr!==3)||result.overflow||!result.controls||!result.inputFloor||
          !result.selected||!result.sample||result.errors.length) throw new Error(JSON.stringify(result));
        currentUrl=result.url;
        console.log(JSON.stringify({viewport,category,...result}));
      }
    }
  }
