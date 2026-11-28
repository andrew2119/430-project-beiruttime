import {spawn, fork} from 'node:child_process';
import {createServer, createConnection} from 'node:net';
import {chmod} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {mkdtemp, rm, writeFile, access, stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve, isAbsolute} from 'node:path';
import {randomUUID} from 'node:crypto';
import {constants} from 'node:fs';

const pause = ms => new Promise(done => setTimeout(done, ms));
// Chrome's helper processes can still write into the profile for a moment after the main process exits.
const REMOVE = {recursive:true, force:true, maxRetries:10, retryDelay:100};
const LAUNCH_ERRORS = ['Installed browser required','Browser closed','Browser command failed','Browser command timed out'];
/** A browser start failure the session can report without leaking paths: a known message or error code, and the failed command. */
export function launchReason(error) {
  const reason = LAUNCH_ERRORS.includes(error?.message) ? error.message
    : typeof error?.code === 'string' && /^E[A-Z]+$/.test(error.code) ? error.code : 'unexpected error';
  return typeof error?.method === 'string' && /^[A-Z][A-Za-z]*\.[a-z][A-Za-z]*$/.test(error.method) ? `${reason} in ${error.method}` : reason;
}
export function navigationMatches(actual, expected) {
  const current = new URL(actual), target = new URL(expected);
  const canonical = path => /^\/(en|ar)\/$/.test(path) ? path.slice(0,-1) : path;
  return current.origin === target.origin && current.search === target.search
    && current.hash === target.hash && canonical(current.pathname) === canonical(target.pathname);
}
export async function navigate(page, path, {origin, cell}, call) {
  const url = new URL(path,origin);
  if (url.origin !== origin) throw new Error('Page must use configured origin');
  if (!/^\/(en|ar)(\/|$)/.test(url.pathname)) url.pathname = `/${cell.locale ?? cell.language}${url.pathname}`;
  if (/^\/(en|ar)\/$/.test(url.pathname)) url.pathname = url.pathname.slice(0,-1);
  const result = await call('Page.navigate',{url:url.href});
  if (result.errorText) throw new Error('Navigation failed');
  const end = Date.now()+12000;
  while (Date.now()<end) {
    const state = await page.evaluate(()=>({href:location.href,ready:document.readyState}));
    if (state.ready === 'complete' && navigationMatches(state.href,url.href)) return;
    await pause(50);
  }
  throw new Error('Navigation timed out');
}

// One click records evidence: the desktop rail's link to the public About page, the click a hosted run has
// seen reach the wrong page. Every other click is the plain press and release, exactly as before.
// For that click the page call that reads the target's box also arms window listeners that note every
// pointerdown, pointerup and click in arrival order, with allowlisted facts only: never an id, a class, a link
// or any text. The record is read back after the release and must carry the nonce the client end made for this
// call. The press, release and click count as this click only when they link up as one mouse click (linkClick);
// a linked press outside the target fails with the line, and every other outcome returns it.
const CLICK_MISS = 'Click landed outside the target', CLICK_EVIDENCE = 'Click evidence';
const CLICK_PROBE = /^\.bt-shell-rail \.bt-shell-navigation a\[href="\/(?:en|ar)\/about"\]$/;
const CLICK_NONCE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CLICK_PAGE = {tags:['a','aside','body','button','div','header','html','img','li','main','nav','path','span','svg','ul'],pointers:['mouse','touch','pen'],limit:8};
const CLICK_RELATIONS = ['target','inside target','target copy','outside','none'];
const clickProbe = (selector,nonce) => typeof selector==='string' && CLICK_PROBE.test(selector) && typeof nonce==='string' && CLICK_NONCE.test(nonce);
function armClick(selector, nonce, {tags, pointers, limit}) {
  const el=document.querySelector(selector);if(!el)throw Error();
  el.scrollIntoView({block:'center'});
  const page=document.scrollingElement??document.documentElement;
  // The nearest ancestor styled to scroll (the rail on desktop), else the page.
  const scroller=node=>{let at=node.parentElement;while(at && !/auto|scroll|overlay/.test(`${getComputedStyle(at).overflowY} ${getComputedStyle(at).overflowX}`))at=at.parentElement;return at??page;};
  const container=scroller(el);
  const classed=(node,name)=>(node?.getAttribute?.('class')??'').split(/\s+/).includes(name);
  const inRail=node=>{for(let at=node;at;at=at.parentElement)if(classed(at,'bt-shell-rail'))return true;return false;};
  const box=node=>{const r=node.getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height};};
  const scroll=()=>({top:container.scrollTop,left:container.scrollLeft,pageX:scrollX,pageY:scrollY});
  const read=box(el),point={x:read.left+read.width/2,y:read.top+read.height/2};
  // The target as the press finds it: the original, else the same-selector copy that was hit or now stands in its place.
  const targetAt=hit=>el.contains(hit) ? el : hit?.closest?.(selector) ?? (el.isConnected ? el : document.querySelector(selector));
  const relation=node=>!node ? 'none' : node===el ? 'target' : el.contains(node) ? 'inside target' : node.closest?.(selector) ? 'target copy' : 'outside';
  // The control a node belongs to, so a hit on a link's label and a hit on the link itself count as the same.
  const owner=node=>{for(let at=node;at;at=at.parentElement){const tag=at.tagName;
    if(['BUTTON','INPUT','LABEL','SELECT','SUMMARY','TEXTAREA'].includes(tag) || tag==='A' && at.getAttribute('href')!==null || at.getAttribute?.('role')==='button')return at;}return null;};
  // A node as allowlisted facts: its tag from a fixed list, whether it is in the rail, and its rail row counted from the target's.
  const place=(node,target)=>{const tag=String(node.tagName??'').toLowerCase(),rows=[...document.querySelectorAll('.bt-shell-navigation a')],own=owner(node);
    return {tag:tags.includes(tag)?tag:'other',rail:inRail(node),row:own && target && rows.includes(own) && rows.includes(target) ? rows.indexOf(own)-rows.indexOf(target) : null};};
  // What the press found: the page's own hit test at the point the press arrived at, and the target's box and scroll.
  const snapshot=(event,at)=>{
    const hit=event.target,under=document.elementFromPoint(at.x,at.y),target=targetAt(hit),now=target?box(target):null,own=owner(hit);
    return {hit:place(hit,target),under:under?{relation:relation(under),...place(under,target)}:null,
      same:!under ? null : under===hit ? 'node' : own && owner(under)===own ? 'owner' : 'neither',
      target:!target?'none':target===el?'original':'fresh copy',
      container:!container.isConnected || target && target!==el && scroller(target)!==container ? 'replaced' : 'same',box:now,scroll:scroll(),
      inside_box:now ? at.x>=now.left && at.x<=now.left+now.width && at.y>=now.top && at.y<=now.top+now.height : null};
  };
  const probe={selector,nonce,container:classed(container,'bt-shell-rail')?'rail':container===page?'page':'other',read:{box:read,scroll:scroll()},events:[],more:0},seen=[];
  const whole=value=>Number.isInteger(value)?value:null;
  const note=event=>{
    if(probe.events.length>=limit){probe.more++;return;}
    const at=Number.isFinite(event.clientX) && Number.isFinite(event.clientY) ? {x:event.clientX,y:event.clientY} : null;
    const item={type:event.type,trusted:event.isTrusted===true,pointer:pointers.includes(event.pointerType)?event.pointerType:event.pointerType===undefined?null:'other',
      id:whole(event.pointerId),button:whole(event.button),detail:whole(event.detail),point:at,relation:relation(event.target)};
    // Only a trusted primary mouse press near the point sent can be the dispatched one, so only such a press is measured.
    if(item.type==='pointerdown')item.snapshot=item.trusted && item.pointer==='mouse' && item.button===0 && at && Math.abs(at.x-point.x)<=1 && Math.abs(at.y-point.y)<=1 ? snapshot(event,at) : null;
    if(item.type==='click')item.prevented=null;
    probe.events.push(item);seen.push(event);
  };
  // A click that reaches the window says whether a page handler on its way took it over.
  const settle=event=>{const at=seen.lastIndexOf(event);if(at>=0 && probe.events[at].type==='click')probe.events[at].prevented=event.defaultPrevented===true;};
  const types=['pointerdown','pointerup','click'];
  window.btClickProbe?.stop();
  for(const type of types)addEventListener(type,note,true);
  addEventListener('click',settle,false);
  probe.stop=()=>{for(const type of types)removeEventListener(type,note,true);removeEventListener('click',settle,false);};
  window.btClickProbe=probe;
  return point;
}
function readClick() {
  const probe=window.btClickProbe;if(!probe)return null;
  probe.stop();delete window.btClickProbe;
  const {selector,nonce,container,read,events,more}=probe;
  return {selector,nonce,container,read,events,more};
}
const near = (a,b) => Object.keys(b).every(name=>Math.abs(a[name]-b[name])<=0.5);
// The press, release and click count as the dispatched click only when they are the only trusted mouse input the
// page saw, in that order, from one pointer, with the primary button, within 1 px of the point sent, and the click
// is a single click. Anything else leaves the press unlinked, which never fails a click.
function linkClick(events, more, sent) {
  const none = {press:null,release:null,click:null};
  if (more>0) return none;
  const [p,r,c,...rest] = events.flatMap((item,index)=>item.trusted && item.pointer==='mouse' ? [index] : []);
  const ours = (index,type) => index!==undefined && events[index].type===type && events[index].button===0 && events[index].id===events[p].id
    && !!events[index].point && Math.abs(events[index].point.x-sent.x)<=1 && Math.abs(events[index].point.y-sent.y)<=1;
  if (rest.length || !ours(p,'pointerdown') || events[p].id===null || !events[p].snapshot) return none;
  if (r===undefined) return {...none,press:p};
  if (!ours(r,'pointerup')) return none;
  if (c===undefined) return {...none,press:p,release:r};
  return ours(c,'click') && events[c].detail===1 ? {press:p,release:r,click:c} : none;
}
// Layout compares the target's box and scroll at the linked press with the read, and is unavailable when the target
// or its scrolling container was replaced; the hit test says whether the page's own hit test at the point the press
// arrived at found the same element or the same control.
function clickEvidence(probe, nonce, sent, record, raw) {
  const events = raw?.events ?? [], linked = raw ? linkClick(events,raw.more,sent) : null;
  const state = at => at==null ? 'not linked' : ['target','inside target','target copy'].includes(events[at].relation) ? 'on target' : 'outside the target';
  const press = linked?.press==null ? null : events[linked.press].snapshot, click = linked?.click==null ? null : events[linked.click];
  return {probe, nonce, sent, record, press:state(linked?.press), release:state(linked?.release), click:state(linked?.click),
    layout:!press || press.target==='none' || press.container==='replaced' ? 'unavailable' : near(press.box,raw.read.box) && near(press.scroll,raw.read.scroll) ? 'unchanged' : 'changed',
    hit_test:!press?.under ? 'unavailable' : press.same==='neither' ? 'differs' : 'agrees',
    activation:click?.prevented===true ? 'default prevented' : click?.prevented===false ? 'not prevented' : 'not observed',
    linked, container:raw?.container ?? null, read:raw?.read ?? null, events:raw ? events : null, more:raw?.more ?? null};
}
// A miss names a cause only when its measurements back it: the layout changed, the point left the target's box and
// the page's hit test agrees with the press; or the layout held and the hit test disagrees. Otherwise the cause is not
// determined. No head claims more than the linked events show.
function clickLine(evidence) {
  const {record,press,release,click,layout,hit_test,linked,events} = evidence;
  const inside = linked?.press==null ? null : events[linked.press].snapshot.inside_box;
  const head = record!=='read' ? `${CLICK_EVIDENCE}: unavailable` : press==='not linked' ? `${CLICK_EVIDENCE}: not linked`
    : press==='outside the target' ? `${CLICK_MISS}: ${layout==='changed' && hit_test==='agrees' && inside===false ? 'layout changed before the press'
      : layout==='unchanged' && hit_test==='differs' ? 'press target differs from the page hit test' : 'cause not determined'}`
    : release==='on target' && click==='on target' ? `${CLICK_EVIDENCE}: linked on target` : `${CLICK_EVIDENCE}: press linked on target, release or click not`;
  return `${head}; evidence ${JSON.stringify(evidence)}`;
}
const keyed = (value,keys) => !!value && typeof value==='object' && !Array.isArray(value) && Object.keys(value).join()===keys;
const numbers = (value,keys) => keyed(value,keys) && Object.values(value).every(Number.isFinite);
const whole = value => value===null || Number.isInteger(value);
const placeShape = (value,keys='tag,rail,row') => keyed(value,keys) && (CLICK_PAGE.tags.includes(value.tag) || value.tag==='other') && typeof value.rail==='boolean' && whole(value.row);
const snapshotShape = value => value===null || keyed(value,'hit,under,same,target,container,box,scroll,inside_box') && placeShape(value.hit)
  && (value.under===null ? value.same===null : placeShape(value.under,'relation,tag,rail,row') && CLICK_RELATIONS.includes(value.under.relation) && ['node','owner','neither'].includes(value.same))
  && ['original','fresh copy','none'].includes(value.target) && ['same','replaced'].includes(value.container)
  && (value.target==='none' ? value.box===null && value.inside_box===null : numbers(value.box,'left,top,width,height') && typeof value.inside_box==='boolean')
  && numbers(value.scroll,'top,left,pageX,pageY');
const eventShape = item => keyed(item,`type,trusted,pointer,id,button,detail,point,relation${item?.type==='pointerdown' ? ',snapshot' : item?.type==='click' ? ',prevented' : ''}`)
  && ['pointerdown','pointerup','click'].includes(item.type) && typeof item.trusted==='boolean' && (item.pointer===null || item.pointer==='other' || CLICK_PAGE.pointers.includes(item.pointer))
  && whole(item.id) && whole(item.button) && whole(item.detail) && (item.point===null || numbers(item.point,'x,y')) && CLICK_RELATIONS.includes(item.relation)
  && (item.type!=='pointerdown' || snapshotShape(item.snapshot)) && (item.type!=='click' || [null,true,false].includes(item.prevented));
const rawShape = raw => keyed(raw,'container,read,events,more') && ['rail','page','other'].includes(raw.container) && keyed(raw.read,'box,scroll')
  && numbers(raw.read.box,'left,top,width,height') && numbers(raw.read.scroll,'top,left,pageX,pageY')
  && Array.isArray(raw.events) && raw.events.length<=CLICK_PAGE.limit && raw.events.every(eventShape) && Number.isInteger(raw.more) && raw.more>=0;
/** Whether a message is exactly a click line under this head for the pending click `args` (the probe and its nonce): evidence of the expected shape that renders back to the same text. */
function clickReported(message, head, args) {
  const match = typeof message==='string' && message.startsWith(`${head}: `) && /; evidence (\{.*\})$/s.exec(message);
  if (!match || !Array.isArray(args) || args.length!==2 || !clickProbe(...args)) return false;
  try {
    const {probe,nonce,sent,record,container,read,events,more} = JSON.parse(match[1]), raw = {container,read,events,more};
    if (probe!==args[0] || nonce!==args[1] || !numbers(sent,'x,y')) return false;
    const valid = record==='read' ? rawShape(raw) : ['none in the page','read-back failed','not this click'].includes(record);
    return valid && clickLine(clickEvidence(probe,nonce,sent,record,record==='read' ? raw : null))===message;
  } catch {return false;}
}
const rounded = value => JSON.parse(JSON.stringify(value,(name,item)=>typeof item==='number' ? Math.round(item*100)/100 : item));
/** Presses and releases the left button on the target's center with real pointer input. For the About probe with its nonce it then returns the click's evidence line, or fails with it when the linked press hit outside the target. */
export async function clickTarget(evaluate, call, selector, nonce) {
  if (!clickProbe(selector,nonce)) {
    const point=await evaluate(selector=>{const el=document.querySelector(selector);if(!el)throw Error();el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};},selector);
    await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
    return;
  }
  const point = await evaluate(armClick,selector,nonce,CLICK_PAGE);
  await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
  // A press that loaded a new page leaves no record and may fail the read; the line then says so, and the caller's own checks judge it.
  let raw = null, record = 'read';
  try {
    const found = await evaluate(readClick);
    if (!found) record = 'none in the page';
    else if (found.selector!==selector || found.nonce!==nonce) record = 'not this click';
    else {const {container,read,events,more} = rounded(found); raw = {container,read,events,more}; if (!rawShape(raw)) {raw = null; record = 'read-back failed';}}
  } catch {raw = null; record = 'read-back failed';}
  const line = clickLine(clickEvidence(selector, nonce, rounded(point), record, raw));
  if (line.startsWith(`${CLICK_MISS}: `)) throw new Error(line);
  return line;
}

async function localBrowser({browserPath, origin, cell, signal}) {
  if (!browserPath || !isAbsolute(browserPath) || signal?.aborted) throw new Error('Installed browser required');
  await access(browserPath,constants.X_OK);
  if(!(await stat(browserPath)).isFile())throw new Error('Installed browser required');
  const profile = await mkdtemp(join(tmpdir(), 'bt-browser-'));
  const child = spawn(browserPath, ['--headless=new', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-pipe', `--user-data-dir=${profile}`, 'about:blank'],
  {stdio:['ignore','ignore','ignore','pipe','pipe']});
  const pending = new Map(); let sequence = 0, buffer = '', sessionId, closed = false, closing;
  const rejectPending = () => { for (const item of pending.values()) item.reject(Object.assign(new Error('Browser closed'),{method:item.method})); pending.clear(); };
  const exited = new Promise(done => {child.once('exit', done); child.once('error', done);});
  child.once('error', rejectPending); child.once('exit', rejectPending);
  child.stdio[4].on('data', chunk => {
    buffer += chunk.toString(); let end;
    while ((end = buffer.indexOf('\0')) >= 0) {
      const message = JSON.parse(buffer.slice(0,end)); buffer = buffer.slice(end+1);
      const item = pending.get(message.id);
      if (item) {pending.delete(message.id); message.error ? item.reject(Object.assign(new Error('Browser command failed'),{method:item.method})) : item.resolve(message.result);}
    }
  });
  async function call(method, params = {}, target = sessionId) {
    if (closed || signal?.aborted) throw new Error('Browser closed');
    const id = ++sequence;
    return new Promise((resolveCall,reject) => {
      const timer = setTimeout(() => {pending.delete(id); reject(Object.assign(new Error('Browser command timed out'),{method}));}, 12000);
      pending.set(id, {method, resolve:value=>{clearTimeout(timer);resolveCall(value);}, reject:error=>{clearTimeout(timer);reject(error);}});
      child.stdio[3].write(JSON.stringify({id,method,params,...(target ? {sessionId:target} : {})})+'\0');
    });
  }
  function close() {
    if (closing) return closing;
    closed = true; rejectPending();
    closing=(async()=>{
      child.kill('SIGTERM');
      const timer = setTimeout(()=>child.kill('SIGKILL'),1000);
      await exited; clearTimeout(timer); await rm(profile,REMOVE);
      signal?.removeEventListener('abort', abort);
    })();
    return closing;
  }
  const abort = () => {close().catch(()=>{});}; signal?.addEventListener('abort',abort,{once:true});
  try {
    const {targetId} = await call('Target.createTarget',{url:'about:blank'},null);
    ({sessionId} = await call('Target.attachToTarget',{targetId,flatten:true},null));
    await call('Page.enable'); await call('Runtime.enable'); await call('Network.enable');
    await call('Network.setExtraHTTPHeaders',{headers:{'Accept-Language':cell.locale ?? cell.language}});
    await call('Network.setCookie',{name:'bt-theme',value:cell.theme,url:origin,path:'/',sameSite:'Lax'});
    await call('Browser.setDownloadBehavior',{behavior:'deny'},null);
    await call('Emulation.setDeviceMetricsOverride',{width:cell.width,height:cell.height,deviceScaleFactor:cell.dpr,mobile:cell.mobile});
    await call('Emulation.setTouchEmulationEnabled',{enabled:cell.touch});
    await call('Emulation.setLocaleOverride',{locale:cell.locale ?? cell.language});
    await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:cell.theme},{name:'prefers-reduced-motion',value:'reduce'}]});
    const page = {
      async evaluate(fn,...args) {
        const result = await call('Runtime.evaluate',{expression:`(${fn.toString()})(...${JSON.stringify(args)})`,awaitPromise:true,returnByValue:true});
        if (result.exceptionDetails) throw new Error('Page evaluation failed');
        return result.result.value;
      },
      goto:path=>navigate(page,path,{origin,cell},call),
      click:(selector,nonce)=>clickTarget(page.evaluate,call,selector,nonce),
      async fill(selector,value) {await page.evaluate((selector,value)=>{const el=document.querySelector(selector);if(!el)throw Error();el.focus();const setter=Object.getOwnPropertyDescriptor(el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;setter.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));},selector,value);},
      async select(selector,value) {await page.evaluate((selector,value)=>{const el=document.querySelector(selector);if(!el)throw Error();el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));},selector,value);},
      async press(key) {const keys={Tab:9,Enter:13,Escape:27};if(!keys[key])throw new Error('Unsupported key');await call('Input.dispatchKeyEvent',{type:'keyDown',key,code:key,windowsVirtualKeyCode:keys[key]});await call('Input.dispatchKeyEvent',{type:'keyUp',key,code:key,windowsVirtualKeyCode:keys[key]});},
      text:selector=>page.evaluate(selector=>document.querySelector(selector)?.textContent ?? null,selector),
      exists:selector=>page.evaluate(selector=>!!document.querySelector(selector),selector),
      async waitFor(selector,{timeout=12000}={}) {const end=Date.now()+timeout;while(Date.now()<end){if(await page.exists(selector))return;await pause(50);}throw new Error('Element timed out');},
      url:()=>page.evaluate(()=>location.href),
      async reload() {await page.goto(await page.url());},
    };
    return {page,call,close,async screenshot(path){const result=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(path,Buffer.from(result.data,'base64'));}};
  } catch(error) {await close().catch(()=>{});throw error;}
}

export const preparationProgram = `
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from connected_walkthrough import Walkthrough
origin, directory, revision = sys.argv[2:5]
walk = Walkthrough(origin, 'native', Path(directory))
original = walk.call
def bound_call(service, method, route, actor=None, *args, **kwargs):
    start = len(walk.evidence)
    try:
        return original(service, method, route, actor, *args, **kwargs)
    finally:
        identity = walk.state.get('accounts', {}).get(actor, {}).get('account', {}).get('id')
        for row in walk.evidence[start:]:
            if identity and row.get('service') == service and row.get('method') == method and row.get('route') == route.split('?')[0]:
                row.setdefault('actor_id', identity)
                row.setdefault('provider_revision', revision)
walk.call = bound_call
try:
    for phase in ['accounts', 'bootstrap', 'onboard', 'contacts']:
        walk.evidence = []
        walk.run_phase(phase)
        path = Path(directory) / (phase + '-bound-evidence.json')
        with open(path, 'w', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(walk.evidence, stream)
finally:
    walk.client.close()
`;
export async function prepare({origin,runDir,revision}, launch=spawn) {
  await new Promise((done,reject)=>{
    const child=launch('python3',['-c',preparationProgram,resolve('tests/integration/sprint-1'),origin,runDir,revision],{stdio:'ignore'});
    const timer=setTimeout(()=>child.kill('SIGTERM'),180000);
    child.once('error',()=>{clearTimeout(timer);reject(new Error('Account preparation unavailable'));});
    child.once('exit',code=>{clearTimeout(timer);code===0?done():reject(new Error('Account preparation failed'));});
  });
}
export function context({page,origin,cell,revision}) {
  const accounts=new Map(); let active;
  const names={'buyer':'buyer-a','buyer2':'buyer-b','private-seller':'seller','dealer':'dealer','brand':'brand','operator':'operator','reviewer':'operator'};
  const uniq=prefix=>`${prefix}-${randomUUID()}`;
  async function request(service,method,path,body,token) {
    if(!/^[a-z][a-z0-9-]*$/.test(service) || typeof path!=='string' || !/^\/(?:internal\/)?v[0-9]+\//.test(path)
      || /[\\#\s]/.test(path))throw new Error('Invalid service request');
    const gatewayPath=`/api/web/v1/${service}${path}`;
    const destination=new URL(gatewayPath,origin);
    if(destination.origin!==origin || destination.pathname+destination.search!==gatewayPath)throw new Error('Invalid service request');
    return page.evaluate(async ({service,method,path,body,token,key})=>{
      const response=await fetch(`/api/web/v1/${service}${path}`,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','Idempotency-Key':key,...(token?{Authorization:`Bearer ${token}`}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
      return {status:response.status,json:await response.json(),operation_id:response.headers.get('x-request-id')};
    },{service,method,path,body,token,key:uniq('n09')});
  }
  async function signIn(role) {
    if(!names[role])throw new Error('Unsupported role');
    const result=await request('identity','POST','/v1/accounts/login',{email:`${names[role]}.s1@example.test`,password:['Course','demo','passphrase!'].join('-')});
    if(result.status!==200 || !result.json.account?.id || !result.json.access_token)throw new Error('Sign in failed');
    const account={actor_id:result.json.account.id,name:result.json.account.display_name,token:result.json.access_token};
    accounts.set(role,account);active=role;
    await page.reload();
    return {actor_id:account.actor_id,name:account.name};
  }
  return {page,origin,cell,revision,uniq,signIn,
    signedInRole:()=>active,
    isActor:id=>[...accounts.values()].some(account=>account.actor_id===id),
    actor:role=>accounts.has(role)&&active===role?Promise.resolve({actor_id:accounts.get(role).actor_id,name:accounts.get(role).name}):signIn(role),
    async api(service,method,path,body,options={}) {const role=options.as ?? active;if(role&&!accounts.has(role))await signIn(role);return request(service,method,path,body,accounts.get(role)?.token);},
  };
}

// The client passes a page error on only when it is listed, or when it is a click miss line for the pending About probe;
// that probe's evidence line goes to the report, so the hosted output shows it whether the click passes or fails.
export async function connectSession(socket, {signal,connect=createConnection,report=line=>console.log(line)}={}) {
  if(typeof socket!=='string' || !isAbsolute(socket))throw new Error('Prepared session unavailable');
  const connection=connect(socket);
  await new Promise((done,reject)=>{connection.once('connect',done);connection.once('error',reject);});
  const pending=new Map();let next=0,buffer='',detached=false;
  const fail=()=>{for(const item of pending.values())item.reject(new Error('Prepared session closed'));pending.clear();};
  connection.on('error',fail);connection.on('close',fail);
  connection.on('data',chunk=>{
    buffer+=chunk;
    let end;
    while((end=buffer.indexOf('\n'))>=0) {
      const message=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
      const item=pending.get(message.id);if(!item)continue;pending.delete(message.id);
      message.error?item.reject(new Error(typeof message.error==='string' && (['Navigation failed','Navigation timed out','Page must use configured origin','Browser closed','Browser command timed out','Session cleanup failed'].includes(message.error) || item.method==='click' && clickReported(message.error,CLICK_MISS,item.args)) ? message.error : 'Prepared page command failed')):item.resolve(message.value);
    }
  });
  function call(method,args=[],closing=false) {
    if(!closing)signal?.throwIfAborted();
    if(connection.destroyed)return Promise.reject(new Error('Prepared session closed'));
    return new Promise((resolve,reject)=>{const id=++next;pending.set(id,{method,args,resolve,reject});connection.write(JSON.stringify({id,method,args})+'\n');});
  }
  const page=Object.fromEntries(['goto','click','fill','select','press','text','exists','waitFor','url','reload'].map(method=>[method,(...args)=>call(method,args)]));
  // Only the About probe gets a fresh nonce, which ties the line the session returns to this one call.
  page.click=async(...args)=>{
    if(args.length!==1 || typeof args[0]!=='string' || !CLICK_PROBE.test(args[0]))return call('click',args);
    const bound=[args[0],randomUUID()],value=await call('click',bound);
    report(clickReported(value,CLICK_EVIDENCE,bound) ? value : 'Click evidence unavailable: the session returned no valid record');
  };
  page.evaluate=(fn,...args)=>call('evaluate',[fn.toString(),...args]);
  return {page,socket,screenshot:path=>call('screenshot',[path]),
    async detach(){await call('detach');detached=true;connection.end();},
    async close(){if(detached || connection.destroyed)return;try{await call('close',[],true);}finally{connection.destroy();}},
  };
}
export async function browser(config) {
  const directory=await mkdtemp(join(tmpdir(),'bt-session-'));
  const socket=join(directory,'page.sock');
  const child=fork(fileURLToPath(import.meta.url),['--session'],{stdio:['ignore','ignore','ignore','ipc'],detached:true});
  try {
    await new Promise((done,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Prepared session timed out')),15000);
      child.once('message',message=>{clearTimeout(timer);message.ready?done():reject(new Error(typeof message.reason==='string' ? `Prepared session unavailable: ${message.reason.slice(0,160)}` : 'Prepared session unavailable'));});
      child.once('error',error=>{clearTimeout(timer);reject(error);});
      child.once('exit',()=>{clearTimeout(timer);reject(new Error('Prepared session closed'));});
      child.send({config:{browserPath:config.browserPath,origin:config.origin,cell:config.cell},socket,directory});
    });
    child.disconnect();child.unref();
    return await connectSession(socket,{signal:config.signal});
  }catch(error){child.kill();await rm(directory,{recursive:true,force:true});throw error;}
}
export async function serveSession({config,socket,directory}, launch=localBrowser,{listen=createServer,secure=chmod}={}) {
  let session,server,timer,stopping;
  // Every caller shares one stop, and the session folder goes even when closing the browser fails.
  const stop=()=>stopping??=(async()=>{
    clearTimeout(timer);server?.close();
    try{await session?.close();}finally{await rm(directory,REMOVE);}
  })();
  const stopQuietly=()=>{stop().catch(()=>{});};
  process.once('SIGTERM',stopQuietly);
  try {
    session=await launch(config);
    server=listen(connection=>{
      let buffer='',detached=false,queue=Promise.resolve();
      connection.on('error',()=>{});
      connection.on('close',()=>{if(!detached)stopQuietly();});
      connection.on('data',chunk=>{
        buffer+=chunk;let end;
        while((end=buffer.indexOf('\n'))>=0) {
          const line=buffer.slice(0,end);buffer=buffer.slice(end+1);
          queue=queue.then(async()=>{
            let message;
            try {
              message=JSON.parse(line);const {method,args}=message;let value;
              if(method==='detach')detached=true;
              else if(method==='close'){await stop();connection.end(JSON.stringify({id:message.id})+'\n');return;}
              else if(method==='screenshot')value=await session.screenshot(...args);
              else if(method==='evaluate')value=await session.page.evaluate(Function('return ('+args[0]+')')(),...args.slice(1));
              else if(['goto','click','fill','select','press','text','exists','waitFor','url','reload'].includes(method)) {
                value=await session.page[method](...args);
                // A click returns only its own probe's line, never one for another call.
                if(method==='click' && !clickReported(value,CLICK_EVIDENCE,args))value=undefined;
              }
              else throw new Error('Unknown page command');
              connection.write(JSON.stringify({id:message.id,value})+'\n');
            }catch(error){connection.write(JSON.stringify({id:message?.id,error:['Navigation failed','Navigation timed out','Page must use configured origin','Browser closed','Browser command timed out'].includes(error.message) || message?.method==='click' && clickReported(error.message,CLICK_MISS,message.args) ? error.message : message?.method==='close' ? 'Session cleanup failed' : true})+'\n');}
          });
        }
      });
    });
    await new Promise((done,reject)=>{server.once('error',reject);server.listen(socket,done);});
    await secure(socket,0o600);
    timer=setTimeout(stopQuietly,30*60*1000);
    process.send?.({ready:true});
    return {close:stop};
  }catch(error){process.send?.({ready:false,reason:launchReason(error)});await stop().catch(()=>{});if(!process.send)throw error;}
}
if(process.argv[2]==='--session' && process.send)process.once('message',message=>{void serveSession(message);});
