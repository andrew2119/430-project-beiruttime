// Run through chrome-devtools-axi run at desktop and true phone emulation.
// This checks real boundary screens, not a signed-in marketplace outcome.
const rows=[];
for(const locale of ['en','ar']) for(const theme of ['light','dark']) {
  for(const route of ['buyer','buyer/auctions/11111111-1111-4111-8111-111111111111']) {
    await page.open(`http://127.0.0.1:3106/${locale}/${route}`);
    await page.wait('main h1');
    await page.wait(1800);
    if(await page.eval(()=>document.documentElement.dataset.theme)!==theme) await page.click('.preferences .icon-button');
    const result=await page.eval(()=>{
      const main=document.querySelector('main'),heading=main.querySelector('h1');
      const controls=[...main.querySelectorAll('.buyer-workspace button,.buyer-workspace a.button,.proxy-panel button,.proxy-panel a.button')].filter(x=>x.getBoundingClientRect().width>0);
      const bounds=[main,heading,...controls].map(x=>({text:x.textContent.slice(0,70),left:x.getBoundingClientRect().left,right:x.getBoundingClientRect().right}));
      return {path:location.pathname,width:innerWidth,height:innerHeight,dpr:devicePixelRatio,lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,
        overflow:document.documentElement.scrollWidth>innerWidth,
        clipped:bounds.filter(r=>r.left<-.5||r.right>innerWidth+.5),
        smallTargets:controls.filter(x=>{const r=x.getBoundingClientRect();return r.height<43.5||r.width<43.5;}).map(x=>x.textContent),
        privateData:main.querySelectorAll('.buyer-activity li,input[id^=maximum-]').length,
        status:[...main.querySelectorAll('[role=status]')].map(x=>x.textContent),
        signIn:main.querySelectorAll('a[href*="/account?next="]').length};
    });
    if(result.lang!==locale||result.dir!==(locale==='ar'?'rtl':'ltr')||result.theme!==theme||result.overflow||result.clipped.length||result.smallTargets.length||result.privateData) throw new Error(JSON.stringify({locale,theme,route,...result}));
    if(!result.status.length&&!result.signIn) throw new Error('No explicit private boundary: '+JSON.stringify(result));
    rows.push(result);
  }
}
console.log(JSON.stringify(rows,null,2));
