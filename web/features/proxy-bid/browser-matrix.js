// Run using the isolated chrome-devtools-axi session's `run` command.
// Set viewport explicitly before each run: 1440x1000x1 or 390x844x1,mobile,touch.
const base='http://127.0.0.1:33517';
const width=await page.eval(()=>innerWidth);
if(![390,1440].includes(width))throw new Error(`Real explicit viewport required, got ${width}`);
const routes={buyer:['buyer','.buyer-activity-row'],bidding:['buyer/auctions/00000000-0000-4000-8000-000000000003','.proxy-panel input'],checkout:['checkout?watch=00000000-0000-4000-8000-000000000006&quote=00000000-0000-4000-8000-000000000004','input[name="watch_id"]'],order:['checkout/00000000-0000-4000-8000-000000000005','.checkout-result'],prices:['prices?quote_id=00000000-0000-4000-8000-000000000004','input[name="subject"]'],buying:['buying?reservation_id=00000000-0000-4000-8000-000000000005&quote_id=00000000-0000-4000-8000-000000000004','input[name="draft_subject"]'],inbox:['inbox','.l07-inbox-row']};
const cases=[];
for(const locale of ['en','ar'])for(const theme of ['light','dark'])for(const [route,[path,selector]] of Object.entries(routes)) {
  await page.eval(`document.cookie='bt-theme=${theme}; Path=/'`);
  await page.open(`${base}/${locale}/${path}`);await page.wait(selector);await page.wait(350);
  await page.press('Tab');
  const row=await page.eval(()=>{
    const main=document.querySelector('main'),header=main.querySelector('.hx-head');
    const visible=el=>el.getBoundingClientRect().width>0&&el.getBoundingClientRect().height>0;
    const controls=[...main.querySelectorAll('button,a,input,textarea')].filter(el=>!el.disabled&&visible(el));
    const textFields=[...main.querySelectorAll('input:not([type=hidden]),textarea')].filter(visible);
    const short=controls.filter(el=>el.getBoundingClientRect().height<43.9).map(el=>({label:el.getAttribute('aria-label')??el.textContent,height:el.getBoundingClientRect().height}));
    const h=getComputedStyle(header),title=getComputedStyle(main.querySelector('h1')),bounds=main.getBoundingClientRect();
    // CP StickyHeader deliberately paints hx-zone::before 48px outside its box.
    // Its clipped veil contributes to scrollWidth, but is not content overflow.
    const contentOverflow=[...main.querySelectorAll('*')].filter(el=>visible(el)&&!el.closest('.hx-tabs-rulerbox')).some(el=>{const r=el.getBoundingClientRect();return r.left<bounds.left-1||r.right>bounds.right+1;});
    return {width:innerWidth,locale:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,documentOverflow:document.documentElement.scrollWidth>innerWidth,rawScrollWidth:main.scrollWidth,contentOverflow,titleCount:main.querySelectorAll('h1').length,focused:document.activeElement!==document.body,shortTargets:short,inputSizes:textFields.map(el=>parseFloat(getComputedStyle(el).fontSize)),header:{padding:h.padding,radius:h.borderRadius,shadow:h.boxShadow,font:title.fontFamily,size:title.fontSize,weight:title.fontWeight},nestedShell:!!main.querySelector('main')};
  });
  const failures=[];
  if(row.width!==width)failures.push('viewport');if(row.locale!==locale||row.dir!==(locale==='ar'?'rtl':'ltr'))failures.push('locale');if(row.theme!==theme)failures.push('theme');if(row.documentOverflow||row.contentOverflow)failures.push('overflow');if(row.titleCount!==1||row.nestedShell)failures.push('structure');if(!row.focused)failures.push('focus');if(width===390&&(row.shortTargets.length||row.inputSizes.some(size=>size<16)))failures.push('phone controls');
  cases.push({route,...row,failures});
}
console.log(JSON.stringify({fixture:'Synthetic visual data through the real BFF, not a connected money proof',passed:cases.every(row=>row.failures.length===0),cases},null,2));
// The caller asserts `passed`; do not throw here, because AXI discards stdout
// when a run throws and that would lose the per-case diagnostic evidence.
