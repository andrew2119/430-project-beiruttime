import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readdir, rm, stat, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createContext, runInContext} from 'node:vm';
import * as ctx from './ctx.mjs';
import {navigate, navigationMatches} from './ctx.mjs';

const cell={locale:'en',theme:'light',width:390,height:844,dpr:1,mobile:true,touch:true};
const quietServer=()=>({once(){},listen(_socket,done){done();},close(){}});
const exists=path=>stat(path).then(()=>true,()=>false);
// Stands in for Chrome: answers browser commands on the debugging pipe, and on SIGTERM leaves a helper
// process rewriting the profile's network state, the way Chrome's network service does, before it exits.
const fakeBrowser=`#!${process.execPath}
const {mkdirSync}=require('node:fs');
const {Socket}=require('node:net');
const {spawn}=require('node:child_process');
const {join}=require('node:path');
const profile=process.argv.find(arg=>arg.startsWith('--user-data-dir=')).slice('--user-data-dir='.length);
mkdirSync(join(profile,'Default'));
// Socket streams, because a pending file stream read on the pipe would stop this process from exiting.
const replies=new Socket({fd:4,readable:false,writable:true});let buffer='';
new Socket({fd:3,readable:true,writable:false}).on('data',chunk=>{
  buffer+=chunk;let end;
  while((end=buffer.indexOf('\\0'))>=0) {
    const {id,method}=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
    replies.write(JSON.stringify({id,result:method==='Target.createTarget'?{targetId:'page'}:method==='Target.attachToTarget'?{sessionId:'page'}:{}})+'\\0');
  }
});
const writer=\`const {renameSync,writeFileSync,writeSync}=require('node:fs');const {join}=require('node:path');
const folder=process.argv[1],end=Date.now()+400;let n=0;writeSync(1,'writing\\\\n');
while(Date.now()<end){try{const temporary=join(folder,'.TransportSecurity.'+n++);writeFileSync(temporary,'{}');renameSync(temporary,join(folder,'TransportSecurity'));}catch(error){if(error.code==='ENOENT')break;throw error;}}\`;
process.on('SIGTERM',()=>{
  const helper=spawn(process.execPath,['-e',writer,join(profile,'Default')],{detached:true,stdio:['ignore','pipe','ignore']});
  helper.stdout.once('data',()=>process.exit(0));
});
`;
async function withTemporaryFolder(run) {
  const root=await mkdtemp(join(tmpdir(),'bt-ctx-test-')),previous=process.env.TMPDIR,temporary=join(root,'tmp');
  await mkdir(temporary);process.env.TMPDIR=temporary;
  try{await run({root,temporary});}
  finally{if(previous===undefined)delete process.env.TMPDIR;else process.env.TMPDIR=previous;await rm(root,{recursive:true,force:true,maxRetries:10,retryDelay:100});}
}

test('root navigation accepts the locale root after redirect',async()=>{
  for(const language of ['en','ar']) {
    const origin='http://localhost:3000';
    for(const path of ['/',`/${language}`,`/${language}/`]) {
      let requested;
      await navigate({evaluate:async()=>({href:`${origin}/${language}`,ready:'complete'})},path,
        {origin,cell:{language}},async(method,params)=>{requested=params.url;return {};});
      assert.equal(requested,`${origin}/${language}`);
    }
    assert.equal(navigationMatches(`${origin}/${language}/?test=1`,`${origin}/${language}?test=1`),true);
    for(const actual of [`http://localhost:3001/${language}`,`${origin}/${language}?test=2`,
      `${origin}/${language}#test`,`${origin}/${language}/help`,`${origin}/${language==='en'?'ar':'en'}`]) {
      assert.equal(navigationMatches(actual,`${origin}/${language}`),false);
    }
    assert.equal(navigationMatches(`${origin}/${language}/help/`,`${origin}/${language}/help`),false);
    await assert.rejects(navigate({},'http://example.test/',{origin,cell:{language}},()=>assert.fail()),/configured origin/);
  }
});

test('closing the browser waits out late profile writes',async()=>{
  await withTemporaryFolder(async({root,temporary})=>{
    const browserPath=join(root,'browser');await writeFile(browserPath,fakeBrowser,{mode:0o700});
    const directory=await mkdtemp(join(temporary,'bt-session-'));
    const handle=await ctx.serveSession({config:{browserPath,origin:'http://127.0.0.1:9',cell},socket:join(directory,'page.sock'),directory},
      undefined,{listen:quietServer,secure:async()=>{}});
    await handle.close();
    assert.deepEqual(await readdir(temporary),[]);
  });
});

test('session folder is removed even when the browser close fails',async()=>{
  await withTemporaryFolder(async({temporary})=>{
    const directory=await mkdtemp(join(temporary,'bt-session-'));
    const handle=await ctx.serveSession({config:{},socket:join(directory,'page.sock'),directory},
      async()=>({close:async()=>{throw new Error('Browser closed');}}),{listen:quietServer,secure:async()=>{}});
    const first=handle.close(),second=handle.close();
    await assert.rejects(first,/Browser closed/);await assert.rejects(second,/Browser closed/);
    assert.equal(await exists(directory),false);
  });
});

test('an unavailable prepared session says why',async()=>{
  await withTemporaryFolder(async({root,temporary})=>{
    await assert.rejects(ctx.browser({browserPath:root,origin:'http://127.0.0.1:9',cell}),
      {message:'Prepared session unavailable: Installed browser required'});
    assert.deepEqual(await readdir(temporary),[]);
  });
});

test('browser start failures report a known reason and the failed command, never a path',()=>{
  assert.equal(ctx.launchReason?.(Object.assign(new Error('Browser command timed out'),{method:'Target.createTarget'})),'Browser command timed out in Target.createTarget');
  assert.equal(ctx.launchReason?.(new Error('Installed browser required')),'Installed browser required');
  assert.equal(ctx.launchReason?.(Object.assign(new Error('EACCES: permission denied, access \'/opt/secret/chrome\''),{code:'EACCES'})),'EACCES');
  assert.equal(ctx.launchReason?.(Object.assign(new Error('/opt/secret/chrome failed'),{method:'/opt/secret'})),'unexpected error');
});

const about='.bt-shell-rail .bt-shell-navigation a[href="/en/about"]',policyLink='.bt-shell-rail .bt-shell-navigation a[href="/en/auction-policy"]';
const phoneAbout='.bt-navigation-sheet[role="dialog"][data-state="open"] .bt-shell-navigation a[href="/en/about"]';
// The nonce the client end makes for one About click, another click's nonce, and the shape every nonce has.
const nonce='0f8d2c4e-6b1a-4c3d-9e7f-2a5b8c1d3e4f',other='7c9e1f3a-2b4d-4e6f-8a0c-1d3e5f7a9b2c';
const nonces=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
// A desktop rail with Auction policy above About, and an account link outside the rail whose id, class, link and text
// must never reach a line. Page code runs the way Runtime.evaluate runs it, so code that leans on anything outside the
// page fails here too. On the press the `before` events arrive first, then `replaced` swaps About for a fresh copy (or
// removes it with 'gone', or swaps the whole rail with 'rail'), `foreign` swaps the page's record for another click's,
// and `move` changes the layout. The press then reaches `hit` at the point `received` gives, where the page's own hit
// test finds `under` (a name, or a function of the point). On the release the `released` events arrive in that order:
// the pointerup at `release` and the click at `click` (none when null), with the pointer ids in `ids` and the click
// count `count`. A page handler on the way up takes every click (`activation` 'prevent'), leaves it ('none'), or stops
// it before it reaches the window ('stop').
function railPage({hit, move=()=>{}, received=point=>point, under=hit, release=hit, click=release, before=[], released=['pointerup','click'],
  ids={}, count=1, activation='prevent', replaced=false, foreign=false, newDocument=false, readFails=false, tamper=null}) {
  const listeners=[],commands=[],hitTests=[];let evaluations=0,armed=0;
  const element=(tag,{id='',className=null,href=null,text='',parent=null,overflow='visible',box=null,selectors=[]})=>{
    const node={tagName:tag.toUpperCase(),id,textContent:text,parentElement:parent,scrollTop:0,scrollLeft:0,overflow,box,isConnected:true,
      getAttribute:name=>({id:id||null,class:className,href})[name] ?? null,scrollIntoView(){},
      // A node taken out of the page has no layout box, as in a browser.
      getBoundingClientRect:()=>node.isConnected ? {...node.box} : {left:0,top:0,width:0,height:0},
      contains:other=>{for(let at=other;at;at=at.parentElement)if(at===node)return true;return false;},
      closest:selector=>{for(let at=node;at;at=at.parentElement)if(at.selectors.includes(selector))return at;return null;},selectors};
    return node;
  };
  const html=element('html',{}),rail=element('aside',{className:'bt-shell-rail',parent:html,overflow:'auto'});
  const list=element('ul',{className:'bt-shell-navigation',parent:rail});
  const link=(href,top,selectors)=>element('a',{className:'bt-shell-link',href,text:href.endsWith('/about')?'About':' Auction\n policy ',parent:list,box:{left:24,top,width:200,height:44},selectors});
  const nodes={html,rail,list,policy:link('/en/auction-policy',357,[policyLink]),about:link('/en/about',400,[about,phoneAbout])};
  nodes.label=element('span',{text:'About',parent:nodes.about});
  nodes.policyLabel=element('span',{text:'Auction policy',parent:nodes.policy});
  nodes.account=element('a',{id:'private-id',className:'private-class',href:'/en/account?key=private-key',text:'private label',parent:html,box:{left:300,top:20,width:120,height:32}});
  // The same-selector copy a re-render puts in About's place, and the fresh rail a whole re-render puts in the rail's.
  nodes.rendered=link('/en/about',400,[about,phoneAbout]);
  nodes.rail2=element('aside',{className:'bt-shell-rail',parent:html,overflow:'auto'});
  nodes.list2=element('ul',{className:'bt-shell-navigation',parent:nodes.rail2});
  nodes.rendered.isConnected=nodes.rail2.isConnected=nodes.list2.isConnected=false;
  rail.scrollTop=43;
  let current=nodes.about;
  const capturing=options=>options===true || options?.capture===true;
  const globals=()=>{const page=createContext({document:{scrollingElement:html,
      querySelector:selector=>[about,phoneAbout].includes(selector)?current:selector===policyLink?nodes.policy:null,
      querySelectorAll:selector=>selector==='.bt-shell-navigation a'?[nodes.policy,current].filter(Boolean):[],
      elementFromPoint:(x,y)=>{hitTests.push({x,y});return nodes[typeof under==='function'?under({x,y}):under]??null;}},
    getComputedStyle:node=>({overflowX:node.overflow,overflowY:node.overflow}),scrollX:0,scrollY:0,
    addEventListener:(type,listener,options)=>{armed++;listeners.push({type,listener,capture:capturing(options)});},
    removeEventListener:(type,listener,options)=>{const at=listeners.findIndex(item=>item.type===type && item.listener===listener && item.capture===capturing(options));if(at>=0)listeners.splice(at,1);}});
    page.window=page;return page;};
  let page=globals();
  // Input reaches the capturing window listeners first, as trusted primary-button mouse input from pointer 1 unless told otherwise.
  const fire=(type,target,point,{isTrusted=true,button=0,pointerType='mouse',pointerId=1,detail=type==='click'?1:0}={})=>{
    const event={type,target:nodes[target],clientX:point.x,clientY:point.y,isTrusted,button,pointerType,pointerId,detail,defaultPrevented:false};
    for(const item of listeners.filter(item=>item.type===type && item.capture))item.listener(event);
    if(type!=='click' || activation==='stop')return;
    if(activation==='prevent')event.defaultPrevented=true;
    for(const item of listeners.filter(item=>item.type===type && !item.capture))item.listener(event);
  };
  return {listeners,commands,nodes,hitTests,get armed(){return armed;},get evaluations(){return evaluations;},
    async evaluate(fn,...args) {
      if(++evaluations>1 && readFails)throw new Error('Page evaluation failed');
      let value;
      try{value=runInContext(`(${fn.toString()})(...${JSON.stringify(args)})`,page);}catch{throw new Error('Page evaluation failed');}
      // `tamper` stands for page code that adds a field to the record it reads back.
      return value===undefined ? undefined : evaluations>1 && tamper ? tamper(JSON.parse(JSON.stringify(value))) : JSON.parse(JSON.stringify(value));
    },
    async call(method,params) {
      commands.push([method,params]);
      const at={x:params.x,y:params.y};
      if(params.type==='mousePressed') {
        for(const [type,target,point=at,options] of before)fire(type,target,point,options);
        if(replaced) {
          nodes.about.isConnected=nodes.label.isConnected=false;nodes.about.parentElement=null;
          if(replaced==='gone')current=null;
          else {nodes.rendered.isConnected=true;current=nodes.rendered;}
          if(replaced==='rail'){rail.isConnected=list.isConnected=false;nodes.rail2.isConnected=nodes.list2.isConnected=true;nodes.rendered.parentElement=nodes.list2;}
        }
        if(foreign)page.btClickProbe.nonce=other;
        move(nodes);fire('pointerdown',hit,received(at));
        if(newDocument){page=globals();listeners.length=0;}
      } else for(const type of released) {
        if(type==='pointerup')fire('pointerup',release,received(at),{pointerId:ids.pointerup});
        else if(click!==null)fire('click',click,received(at),{pointerId:ids.click,detail:count});
      }
      return {};
    }};
}
const pressAndRelease=point=>['mousePressed','mouseReleased'].map(type=>['Input.dispatchMouseEvent',{type,button:'left',clickCount:1,...point}]);
// The rail scrolls back by 43 pixels between the read and the press, so Auction policy sits under the point.
const railMoved=nodes=>{nodes.rail.scrollTop=0;nodes.policy.box={...nodes.policy.box,top:400};nodes.about.box={...nodes.about.box,top:443};};
const center={x:124,y:422},read={box:{left:24,top:400,width:200,height:44},scroll:{top:43,left:0,pageX:0,pageY:0}};
const evidence=line=>JSON.parse(line.slice(line.indexOf('; evidence ')+'; evidence '.length));
const heads=({line,failure})=>(line ?? failure).slice(0,(line ?? failure).indexOf('; evidence '));
// What the helper notes for one event, and what it measures for a press that can be the dispatched one.
const noted=(type,relation,extra={},point=center)=>({type,trusted:true,pointer:'mouse',id:1,button:0,detail:type==='click'?1:0,point,relation,...extra});
const place=(tag,row,rail=true)=>({tag,rail,row});
const measured=(fields={})=>({hit:place('a',0),under:{relation:'target',...place('a',0)},same:'node',target:'original',container:'same',box:read.box,scroll:read.scroll,inside_box:true,...fields});
const onAbout=[noted('pointerdown','target',{snapshot:measured()}),noted('pointerup','target'),noted('click','target',{prevented:true})];
// The exact line for an About probe click with the first nonce: a linked click on the target unless told otherwise.
const lineFor=(head,fields={})=>`${head}; evidence ${JSON.stringify({probe:about,nonce,sent:center,record:'read',press:'on target',release:'on target',click:'on target',
  layout:'unchanged',hit_test:'agrees',activation:'default prevented',linked:{press:0,release:1,click:2},container:'rail',read,events:onAbout,more:0,...fields})}`;
// One About probe click on a fresh rail page: the same two commands go out at the read point and the listeners are gone
// afterwards, unless the read-back failed and could not remove them.
async function clickOn(options) {
  const page=railPage(options);
  const outcome=await ctx.clickTarget(page.evaluate,page.call,about,nonce).then(line=>({line}),error=>({failure:error.message}));
  assert.deepEqual(page.commands,pressAndRelease(center));
  if(!options.readFails)assert.equal(page.listeners.length,0);
  return outcome;
}

test('a press, release and click linked as one mouse click on the target say so',async()=>{
  assert.deepEqual(await clickOn({hit:'about'}),{line:lineFor('Click evidence: linked on target')});
  assert.deepEqual(await clickOn({hit:'label'}),{line:lineFor('Click evidence: linked on target',{events:[noted('pointerdown','inside target',
    {snapshot:measured({hit:place('span',0),under:{relation:'inside target',...place('span',0)}})}),noted('pointerup','inside target'),noted('click','inside target',{prevented:true})]})});
});

test('a linked press on the target whose release or click is elsewhere or missing says only the press is linked on target',async()=>{
  for(const [options,release,click,activation] of [[{hit:'about',release:'policy'},'outside the target','outside the target','default prevented'],
    [{hit:'about',click:null},'on target','not linked','not observed']]) {
    const outcome=await clickOn(options),found=evidence(outcome.line);
    assert.equal(heads(outcome),'Click evidence: press linked on target, release or click not');
    assert.deepEqual([found.press,found.release,found.click,found.activation],['on target',release,click,activation]);
  }
});

test('a click with no record of its own says the evidence is unavailable and leaves the judgement to the caller',async()=>{
  const unavailable=record=>lineFor('Click evidence: unavailable',{record,press:'not linked',release:'not linked',click:'not linked',layout:'unavailable',
    hit_test:'unavailable',activation:'not observed',linked:null,container:null,read:null,events:null,more:null});
  assert.deepEqual(await clickOn({hit:'policy',newDocument:true}),{line:unavailable('none in the page')});
  assert.deepEqual(await clickOn({hit:'policy',readFails:true}),{line:unavailable('read-back failed')});
  assert.deepEqual(await clickOn({hit:'policy',move:railMoved,foreign:true}),{line:unavailable('not this click')});
  const missing=railPage({hit:'about'});
  await assert.rejects(ctx.clickTarget(missing.evaluate,missing.call,about.replace('/en/','/ar/'),nonce),{message:'Page evaluation failed'});
  assert.deepEqual(missing.commands,[]);
});

test('a linked press outside the target names the layout only when it changed, the point left the box and the page hit test agrees',async()=>{
  const outside=fields=>[noted('pointerdown','outside',{snapshot:measured({hit:place('a',-1),under:{relation:'outside',...place('a',-1)},...fields})}),
    noted('pointerup','outside'),noted('click','outside',{prevented:true})];
  const missed={press:'outside the target',release:'outside the target',click:'outside the target',layout:'changed'};
  assert.deepEqual(await clickOn({hit:'policy',move:railMoved}),{failure:lineFor('Click landed outside the target: layout changed before the press',
    {...missed,events:outside({box:{...read.box,top:443},scroll:{...read.scroll,top:0},inside_box:false})})});
  // The rail shifts by 10 pixels only, so the point is still inside About's box and something else is on top of it: the cause stays open.
  const shifted=nodes=>{nodes.rail.scrollTop=33;nodes.about.box={...nodes.about.box,top:410};};
  assert.deepEqual(await clickOn({hit:'policy',move:shifted}),{failure:lineFor('Click landed outside the target: cause not determined',
    {...missed,events:outside({box:{...read.box,top:410},scroll:{...read.scroll,top:33},inside_box:true})})});
});

test('a linked press outside names the hit test only when it differs and the layout held, and otherwise leaves the cause open',async()=>{
  for(const [options,cause,layout,hitTest] of [[{hit:'policy',under:'about'},'press target differs from the page hit test','unchanged','differs'],
    [{hit:'policy',under:'about',move:railMoved},'cause not determined','changed','differs'],[{hit:'policy'},'cause not determined','unchanged','agrees']]) {
    const outcome=await clickOn(options);
    assert.equal(heads(outcome),`Click landed outside the target: ${cause}`);
    assert.deepEqual([evidence(outcome.failure).layout,evidence(outcome.failure).hit_test],[layout,hitTest]);
  }
  const {snapshot}=evidence((await clickOn({hit:'policy',under:'about'})).failure).events[0];
  assert.deepEqual([snapshot.under,snapshot.same],[{relation:'target',...place('a',0)},'neither']);
});

test('the page hit test is taken where the press arrived, so a press across a boundary is not a delivery fault',async()=>{
  // The boundary between About and Auction policy runs between the point sent and the point the press arrived at.
  const page=railPage({hit:'policy',received:point=>({x:point.x,y:point.y+0.75}),under:point=>point.y>422.5?'policy':'about'});
  const failure=await ctx.clickTarget(page.evaluate,page.call,about,nonce).then(()=>assert.fail('expected a miss'),error=>error.message);
  assert.deepEqual(page.hitTests,[{x:124,y:422.75}]);
  assert.equal(heads({failure}),'Click landed outside the target: cause not determined');
  const found=evidence(failure);
  assert.deepEqual([found.hit_test,found.layout,found.events[0].point,found.linked],['agrees','unchanged',{x:124,y:422.75},{press:0,release:1,click:2}]);
});

test('a hit on a link while the page hit test finds its label, or the reverse, counts as the same control',async()=>{
  const {line}=await clickOn({hit:'about',under:'label'});
  assert.equal(heads({line}),'Click evidence: linked on target');
  assert.deepEqual([evidence(line).hit_test,evidence(line).events[0].snapshot.same],['agrees','owner']);
  const {failure}=await clickOn({hit:'policyLabel',under:'policy',move:railMoved});
  assert.equal(heads({failure}),'Click landed outside the target: layout changed before the press');
  const {snapshot}=evidence(failure).events[0];
  assert.deepEqual([evidence(failure).hit_test,snapshot.same,snapshot.hit,snapshot.under],['agrees','owner',place('span',-1),{relation:'outside',...place('a',-1)}]);
});

// Input that cannot be the dispatched press: an untrusted press, trusted touch and pen presses at the point sent, and an untrusted click.
const otherInput=[['pointerdown','policy',undefined,{isTrusted:false}],['pointerdown','policy',undefined,{pointerType:'touch',pointerId:7}],
  ['pointerdown','policy',undefined,{pointerType:'pen',pointerId:9}],['click','policy',undefined,{isTrusted:false}]];
test('input that is untrusted or from another pointer is noted but never taken for the dispatched click',async()=>{
  const {line}=await clickOn({hit:'about',before:otherInput});
  assert.equal(heads({line}),'Click evidence: linked on target');
  const found=evidence(line);
  assert.deepEqual(found.linked,{press:4,release:5,click:6});
  assert.deepEqual(found.events.slice(0,4).map(item=>[item.type,item.trusted,item.pointer,item.id,item.snapshot ?? null]),
    [['pointerdown',false,'mouse',1,null],['pointerdown',true,'touch',7,null],['pointerdown',true,'pen',9,null],['click',false,'mouse',1,null]]);
  const {failure}=await clickOn({hit:'policy',move:railMoved,before:otherInput});
  assert.equal(heads({failure}),'Click landed outside the target: layout changed before the press');
  assert.equal(evidence(failure).linked.press,4);
});

test('other trusted mouse input leaves the click not linked, so it never fails, even when the press misses',async()=>{
  // A second press at the point sent, a right-button press there and a press 43 pixels higher, each trusted and from the mouse.
  for(const extra of [['pointerdown','policy'],['pointerdown','policy',undefined,{button:2}],['pointerdown','policy',{x:124,y:379}]]) {
    for(const options of [{hit:'about'},{hit:'policy',move:railMoved}]) {
      const outcome=await clickOn({...options,before:[extra]});
      assert.equal(heads(outcome),'Click evidence: not linked',JSON.stringify(extra));
      assert.deepEqual([evidence(outcome.line).linked,evidence(outcome.line).layout],[{press:null,release:null,click:null},'unavailable']);
    }
  }
});

test('a release or click out of order, from another pointer or counted twice, or a record overflow, leaves the click not linked',async()=>{
  for(const options of [{released:['click','pointerup']},{ids:{pointerup:2}},{ids:{click:2}},{count:2}]) {
    for(const missed of [false,true]) {
      const outcome=await clickOn({hit:missed?'policy':'about',move:missed?railMoved:undefined,...options});
      assert.equal(heads(outcome),'Click evidence: not linked',JSON.stringify(options));
    }
  }
  const flood=Array.from({length:8},()=>['pointerdown','policy',undefined,{isTrusted:false}]);
  const outcome=await clickOn({hit:'policy',move:railMoved,before:flood});
  assert.equal(heads(outcome),'Click evidence: not linked');
  assert.deepEqual([evidence(outcome.line).events.length,evidence(outcome.line).more],[8,3]);
});

test('a press that arrives only at another point is not taken for the dispatched one',async()=>{
  const far={x:124,y:379},outcome=await clickOn({hit:'policy',received:()=>({x:124.004,y:378.996})}),found=evidence(outcome.line);
  assert.equal(heads(outcome),'Click evidence: not linked');
  assert.deepEqual([found.press,found.release,found.click,found.layout,found.hit_test,found.activation],['not linked','not linked','not linked','unavailable','unavailable','not observed']);
  assert.deepEqual(found.events,[noted('pointerdown','outside',{snapshot:null},far),noted('pointerup','outside',{},far),noted('click','outside',{prevented:true},far)]);
});

test('a fresh same-selector copy is judged by its own box, and a replaced rail or a gone target leaves the layout unavailable',async()=>{
  const press=outcome=>{const found=evidence(outcome.line ?? outcome.failure),{snapshot}=found.events[found.linked.press];
    return {target:snapshot.target,container:snapshot.container,box:snapshot.box,layout:found.layout};};
  const fresh=await clickOn({hit:'rendered',replaced:true});
  assert.equal(heads(fresh),'Click evidence: linked on target');
  assert.deepEqual([press(fresh),evidence(fresh.line).events[0].relation],[{target:'fresh copy',container:'same',box:read.box,layout:'unchanged'},'target copy']);
  const beside=await clickOn({hit:'policy',replaced:true});
  assert.equal(heads(beside),'Click landed outside the target: cause not determined');
  assert.deepEqual(press(beside),{target:'fresh copy',container:'same',box:read.box,layout:'unchanged'});
  const gone=await clickOn({hit:'policy',replaced:'gone'});
  assert.equal(heads(gone),'Click landed outside the target: cause not determined');
  assert.deepEqual(press(gone),{target:'none',container:'same',box:null,layout:'unavailable'});
  const rebuilt=await clickOn({hit:'rendered',replaced:'rail'});
  assert.equal(heads(rebuilt),'Click evidence: linked on target');
  assert.deepEqual(press(rebuilt),{target:'fresh copy',container:'replaced',box:read.box,layout:'unavailable'});
  // A replaced rail gives no layout cause even when the old rail's scroll and boxes look moved.
  const moved=await clickOn({hit:'policy',replaced:'rail',move:railMoved});
  assert.equal(heads(moved),'Click landed outside the target: cause not determined');
  assert.equal(evidence(moved.failure).layout,'unavailable');
});

test('the click records whether a page handler took it over on its way to the window, and the head never depends on it',async()=>{
  for(const [activation,expected,prevented] of [['prevent','default prevented',true],['none','not prevented',false],['stop','not observed',null]]) {
    const {line}=await clickOn({hit:'about',activation});
    assert.equal(heads({line}),'Click evidence: linked on target');
    assert.deepEqual([evidence(line).activation,evidence(line).events[2].prevented],[expected,prevented]);
  }
});

test('only the About probe with a nonce collects evidence; every other click is the plain press and release',async()=>{
  for(const [selector,key,point] of [[policyLink,nonce,{x:124,y:379}],[about,undefined,center],[about,'not-a-nonce',center],
    [about,nonce.toUpperCase(),center],[phoneAbout,nonce,center]]) {
    const page=railPage({hit:'policy',move:railMoved});
    assert.equal(await ctx.clickTarget(page.evaluate,page.call,selector,key),undefined);
    assert.deepEqual([page.commands,page.armed,page.evaluations,page.hitTests],[pressAndRelease(point),0,1,[]]);
  }
});

test('a line carries only allowlisted facts, never an id, a class, a link or any text from the page',async()=>{
  // Unrelated trusted touch input and an untrusted click reach the account link first; then the press lands on About, or on the account link.
  const before=[['pointerdown','account',undefined,{pointerType:'touch',pointerId:7}],['click','account',undefined,{isTrusted:false}]];
  const lines=[(await clickOn({hit:'about',before})).line,(await clickOn({hit:'account',before})).failure];
  assert.deepEqual(lines.map(line=>heads({line})),['Click evidence: linked on target','Click landed outside the target: cause not determined']);
  for(const line of lines) {
    const {probe,...rest}=evidence(line);
    assert.equal(probe,about);
    assert.doesNotMatch(JSON.stringify(rest)+heads({line}),/private|account|href|bt-shell|\/en\/|About|Auction/);
    for(const item of rest.events)assert.ok(Object.keys(item).every(name=>['type','trusted','pointer','id','button','detail','point','relation','snapshot','prevented'].includes(name)));
  }
  assert.deepEqual(evidence(lines[1]).events[2].snapshot.hit,place('a',null,false));
  // A record with any field beyond the allowlist, at any depth, is never passed on.
  for(const tamper of [found=>{found.events[0].href='/en/account?key=private-key';return found;},found=>{found.events[0].snapshot.hit.text='private label';return found;},
    found=>{found.read.box.label='private label';return found;}]) {
    const {line}=await clickOn({hit:'about',tamper});
    assert.deepEqual([heads({line}),evidence(line).record,evidence(line).events],['Click evidence: unavailable','read-back failed',null]);
  }
});

// The lines a session end can return for the About probe with this nonce, made by the real helper.
async function clickLines(key=nonce) {
  const missed=railPage({hit:'policy',move:railMoved}),landed=railPage({hit:'about'});
  return {miss:await ctx.clickTarget(missed.evaluate,missed.call,about,key).then(()=>assert.fail('expected a miss'),error=>error.message),
    correct:await ctx.clickTarget(landed.evaluate,landed.call,about,key)};
}
const none='Click evidence unavailable: the session returned no valid record';
// The same line said to be for the Arabic About link, every other part intact.
const otherProbe=line=>{const swapped=line.replace('\\"/en/about\\"','\\"/ar/about\\"');assert.notEqual(swapped,line);return swapped;};
// The same line with a link added to its first event, which still renders back to the same text.
const withLink=line=>{const added=line.replace('"relation":"','"href":"/en/account?key=private-key","relation":"');assert.notEqual(added,line);return added;};

test('the prepared session passes on only a click miss bound to the pending click, and returns only that click\'s line',async()=>{
  const stale=await clickLines(other);
  const root=await mkdtemp(join(tmpdir(),'bt-click-')),directory=join(root,'session'),socket=join(directory,'page.sock');
  let click,given;const lines=[],calls=[],replies=[];
  // What the session end itself writes back, before the client's own check.
  const {createConnection}=await import('node:net');
  const connect=path=>{const connection=createConnection(path);let buffer='';
    connection.on('data',chunk=>{buffer+=chunk;let end;while((end=buffer.indexOf('\n'))>=0){replies.push(JSON.parse(buffer.slice(0,end)));buffer=buffer.slice(end+1);}});
    return connection;};
  // The session end's click runs the real helper with what the client sent, and keeps what the helper gave back.
  const real=options=>async(...args)=>{calls.push(args);const page=railPage(options);
    return ctx.clickTarget(page.evaluate,page.call,...args).then(line=>given=line,error=>{given=error.message;throw error;});};
  try {
    await mkdir(directory);
    await ctx.serveSession({config:{},socket,directory},async()=>({close:async()=>{},
      page:{click:(...args)=>click(...args),text:async()=>{throw new Error(stale.miss);}}}));
    const session=await ctx.connectSession(socket,{connect,report:line=>lines.push(line)});
    try {
      click=real({hit:'policy',move:railMoved});
      await assert.rejects(session.page.click(about),error=>error.message===given);
      assert.equal(heads({failure:given}),'Click landed outside the target: layout changed before the press');
      click=real({hit:'about'});
      assert.equal(await session.page.click(about),undefined);
      assert.deepEqual(lines,[given]);
      assert.ok(calls.every(([selector,key])=>selector===about && nonces.test(key)) && calls[0][1]!==calls[1][1] && evidence(given).nonce===calls[1][1]);
      // Any other click goes out as it came and leaves no line.
      click=real({hit:'policy'});
      assert.equal(await session.page.click(policyLink),undefined);
      assert.deepEqual([calls.at(-1),lines.length],[[policyLink],1]);
      await assert.rejects(session.page.text('main'),{message:'Prepared page command failed'});
      // A well-formed line for another click, or for the other About link, is dropped at this end.
      for(const make of [async()=>stale.correct,async key=>otherProbe((await clickLines(key)).correct),async key=>withLink((await clickLines(key)).correct)]) {
        click=async(selector,key)=>make(key);
        assert.equal(await session.page.click(about),undefined);
      }
      assert.deepEqual([lines.slice(1),replies.slice(-3).map(reply=>Object.keys(reply))],[[none,none,none],[['id'],['id'],['id']]]);
      for(const make of [async()=>stale.miss,async key=>otherProbe((await clickLines(key)).miss),async key=>withLink((await clickLines(key)).miss),async()=>`Click landed outside the target: ${root} failed`,
        async key=>(await clickLines(key)).miss.replace(': layout changed before the press;',': cause not determined;'),async key=>`${(await clickLines(key)).miss} `]) {
        click=async(selector,key)=>{throw new Error(await make(key));};
        await assert.rejects(session.page.click(about),{message:'Prepared page command failed'});
      }
      assert.equal(lines.length,4);
    } finally {await session.close();}
  } finally {await rm(root,{recursive:true,force:true});}
});

test('the client also passes on only a click miss bound to its pending click, and reports only a bound line',async t=>{
  const {duplexPair}=await import('node:stream');
  const stale=await clickLines(other);
  // A session end that answers each command with what `reply` makes of it, unfiltered.
  let reply=()=>({}),given;const sent=[];
  const connect=()=>{const [client,host]=duplexPair();let buffer='';host.on('error',()=>{});
    host.on('data',chunk=>{buffer+=chunk;let end;while((end=buffer.indexOf('\n'))>=0){const message=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);sent.push(message);
      Promise.resolve(reply(message)).then(answer=>host.write(JSON.stringify({id:message.id,...answer})+'\n'));}});
    queueMicrotask(()=>client.emit('connect'));return client;};
  const socket=join(tmpdir(),'bt-unused.sock'),lines=[];
  const session=await ctx.connectSession(socket,{connect,report:line=>lines.push(line)});
  reply=()=>({error:stale.miss});
  await assert.rejects(session.page.text('main'),{message:'Prepared page command failed'});
  reply=async({args})=>({error:given=(await clickLines(args[1])).miss});
  await assert.rejects(session.page.click(about),error=>error.message===given);
  for(const make of [()=>stale.miss,async({args})=>otherProbe((await clickLines(args[1])).miss),async({args})=>withLink((await clickLines(args[1])).miss),
    async({args})=>(await clickLines(args[1])).miss.replace(': layout changed before the press;',': cause not determined;'),()=>'Click landed outside the target: elsewhere',()=>true]) {
    reply=async message=>({error:await make(message)});
    await assert.rejects(session.page.click(about),{message:'Prepared page command failed'});
  }
  reply=async({args})=>({value:given=(await clickLines(args[1])).correct});
  assert.equal(await session.page.click(about),undefined);
  for(const make of [()=>stale.correct,async({args})=>otherProbe((await clickLines(args[1])).correct),async({args})=>withLink((await clickLines(args[1])).correct),async({args})=>(await clickLines(args[1])).miss,
    ()=>'Click evidence: linked on target; evidence {}',()=>undefined]) {
    reply=async message=>({value:await make(message)});
    assert.equal(await session.page.click(about),undefined);
  }
  assert.deepEqual(lines,[given,none,none,none,none,none,none]);
  // Any other click goes out with its own arguments only and leaves no line.
  reply=()=>({});
  assert.equal(await session.page.click(policyLink),undefined);
  assert.deepEqual([sent.at(-1).args,lines.length],[[policyLink],7]);
  const keys=sent.filter(message=>message.method==='click' && message.args[0]===about).map(message=>message.args[1]);
  assert.ok(keys.length===14 && keys.every(key=>nonces.test(key)) && new Set(keys).size===keys.length);
  const printed=t.mock.method(console,'log',()=>{});
  const quiet=await ctx.connectSession(socket,{connect});
  reply=async({args})=>({value:given=(await clickLines(args[1])).correct});
  await quiet.page.click(about);
  assert.deepEqual(printed.mock.calls.map(call=>call.arguments),[[given]]);
  reply=()=>({});
  await session.close();await quiet.close();
});
