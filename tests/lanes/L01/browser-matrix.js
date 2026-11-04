// Run through chrome-devtools-axi run after selecting the intended viewport.
const rows=[];
for (const locale of ['en','ar']) {
  for (const theme of ['light','dark']) {
    for (const route of ['account','seller/verification','consent']) {
      await page.open(`http://localhost:3101/${locale}/${route}`);
      await page.wait('.identity-page');
      let ready=false;
      for(let attempt=0;attempt<50;attempt++) {
        ready=await page.eval(()=>{
          const path=location.pathname;
          const loading=[...document.querySelectorAll('.identity-page [role=status]')].some(x=>x.textContent.includes('Loading')||x.textContent.includes('تحميل'));
          const content=path.endsWith('/account')?document.querySelector('input[name=current_password]'):path.endsWith('/seller/verification')?document.querySelector('.identity-status'):document.querySelector('input[name=request_id]');
          return Boolean(content)&&!loading;
        });
        if(ready)break;
        await page.wait(100);
      }
      if(!ready)throw new Error('Authenticated private screen did not become ready: '+locale+'/'+route);
      const initial=await page.eval(()=>document.documentElement.dataset.theme);
      if(initial!==theme) await page.click('.preferences .icon-button');
      const result=await page.eval(()=>{
        const viewport={width:innerWidth,height:innerHeight,dpr:devicePixelRatio};
        const frame=document.querySelector('main').getBoundingClientRect();
        const controls=[...document.querySelectorAll('.identity-page input:not([type=hidden]):not([type=radio]),.identity-page button,.identity-page a.button')].filter(x=>x.getBoundingClientRect().width>0);
        return {viewport,lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,title:document.querySelector('h1')?.textContent,overflow:document.documentElement.scrollWidth>innerWidth,
          frameOutsideViewport:frame.left<-.5||frame.right>innerWidth+.5,
          clipped:controls.filter(x=>{const r=x.getBoundingClientRect();return r.left<Math.max(0,frame.left)-1||r.right>Math.min(innerWidth,frame.right)+1;}).map(x=>x.name||x.textContent),
          smallTargets:controls.filter(x=>{const r=x.getBoundingClientRect();return r.width<43.5||r.height<43.5;}).map(x=>x.name||x.textContent),
          smallInputFonts:controls.filter(x=>x.tagName==='INPUT'&&parseFloat(getComputedStyle(x).fontSize)<16).map(x=>x.name),
          smallRadioLabels:[...document.querySelectorAll('.identity-page input[type=radio]')].filter(x=>x.closest('label').getBoundingClientRect().height<43.5).map(x=>x.value),
          errors:[...document.querySelectorAll('.identity-page [role=alert]')].map(x=>x.textContent)};
      });
      if(result.overflow||result.frameOutsideViewport||result.clipped.length||result.smallTargets.length||result.smallInputFonts.length||result.smallRadioLabels.length||result.errors.length) throw new Error('Viewport/interaction contract failed: '+JSON.stringify({locale,theme,route,...result}));
      rows.push({locale,theme,route,...result});
    }
  }
}
console.log(JSON.stringify(rows,null,2));
