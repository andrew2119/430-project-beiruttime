// All owned screens, real refresh-cookie restoration, no injected client identity.
const results = [];
async function login(email) {
  const response = await page.eval(`(async () => {
    const response=await fetch('/api/web/v1/identity/v1/accounts/login',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(${JSON.stringify({email,password:fixture.sample_password})})
    });return response.status;
  })()`);
  if(response !== 200) throw new Error('Real login failed: '+response);
}
const pages = [
  {path:'/business',ready:'input[name=legal_name]'},
  {path:'/business/contacts',ready:'input[name=recipient]'},
  {path:'/business/membership',ready:'input[name=subject]'},
  {path:'/operations/verification',ready:'input[name=application]'},
  {path:'/business/review-history',ready:'.business-workspace ol'},
];
await page.open('http://localhost:3202/en/business');
for (const item of pages) {
  await login(item.path.endsWith('review-history') ? `sample-browser-${fixture.operator_email}` : fixture.operator_email);
  for (const locale of ['en','ar']) for(const theme of ['light','dark']) {
    await page.eval(`document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`);
    const navigation = await page.open('http://localhost:3202/'+locale+item.path);
    await page.wait(item.ready);
    if(item.path === '/operations/verification') {
      await page.click('.business-queue button');
      await page.wait('input[name=application_revision]');
    }
    const result = await page.eval(() => ({
      path:location.pathname,width:innerWidth,dpr:devicePixelRatio,
      locale:document.documentElement.lang,dir:document.documentElement.dir,
      theme:document.documentElement.dataset.theme,
      documentWidth:document.documentElement.scrollWidth,
      title:document.querySelector('h1')?.textContent,
      alerts:[...document.querySelectorAll('.business-feedback[role=alert]')].map(el=>el.textContent),
      clipped:[...document.querySelectorAll('.business-heading,.business-heading p,.business-form,.business-field,.business-workspace ol,.business-queue')]
        .filter(el=>el.scrollWidth>el.clientWidth+1).map(el=>el.className),
      smallTargets:[...document.querySelectorAll('main a,main button,main select,main input:not([type=checkbox]),.business-check,.business-checks label')]
        .filter(el=>{const box=el.getBoundingClientRect();return box.height>0&&(box.width<43.5||box.height<43.5);})
        .map(el=>el.textContent||el.getAttribute('name')),
      smallFonts:innerWidth<=850 ? [...document.querySelectorAll('main input:not([type=checkbox]),main select')].filter(el=>parseFloat(getComputedStyle(el).fontSize)<16).map(el=>el.name) : [],
      privateHistory:location.pathname.endsWith('review-history') ? document.querySelector('main').innerText.includes('Sample identity and possession references checked independently') : undefined,
    }));
    if(navigation.status!==200 || ![390,1440].includes(result.width) || result.locale!==locale || result.dir!==(locale==='ar'?'rtl':'ltr') || result.theme!==theme || result.documentWidth>result.width+1 || result.alerts.length || result.clipped.length || result.smallTargets.length || result.smallFonts.length || result.privateHistory===false)
      throw new Error('Private matrix failed: '+JSON.stringify(result));
    results.push(result);
  }
}
console.log(JSON.stringify(results,null,2));
