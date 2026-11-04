// State faces through the real application, using explicit synthetic fixture modes.
const origin='http://127.0.0.1:33517',locale=await page.eval(()=>document.documentElement.lang),width=await page.eval(()=>innerWidth);
const routes={buyer:'buyer',bidding:'buyer/auctions/00000000-0000-4000-8000-000000000003',checkout:'checkout',order:'checkout/00000000-0000-4000-8000-000000000005',prices:'prices',buying:'buying',inbox:'inbox'};
const cases=[];
for(const mode of ['slow','empty','signed-out','error']) {
 await fetch(`http://127.0.0.1:33516/__proof?reset=1&mode=${mode}`);
 for(const [route,path] of Object.entries(routes)) {
  if(mode==='empty'&&['bidding','order'].includes(route))continue;
  try {
   await page.open(`${origin}/${locale}/${path}`);
   await page.wait(mode==='slow'?'.buyer-loading':mode==='error'?'.buyer-section-state[data-kind="error"],.l07-error':mode==='signed-out'?'.buyer-section-state[data-kind="locked"]':'.buyer-section-state');
   const state=await page.eval(()=>({locale:document.documentElement.lang,dir:document.documentElement.dir,width:innerWidth,body:document.querySelector('main').innerText,inputCount:document.querySelectorAll('main input').length,skeletonCount:document.querySelectorAll('main .pg-skeleton').length,overflow:document.documentElement.scrollWidth>innerWidth}));
   const passed=state.locale===locale&&state.width===width&&!state.overflow&&(mode!=='signed-out'||state.inputCount===0)&&(mode!=='slow'||state.skeletonCount>0);
   cases.push({mode,route,...state,passed});
   if(mode==='slow')await page.wait(1500);
  }catch(error){cases.push({mode,route,passed:false,error:String(error)});}
 }
}
await fetch('http://127.0.0.1:33516/__proof?reset=1');
console.log(JSON.stringify({synthetic:true,passed:cases.every(row=>row.passed),cases},null,2));
