import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require=createRequire(new URL('../../../../web/package.json',import.meta.url));
const ts=require('typescript');
const source=readFileSync(new URL('../../../../web/features/maintenance/submission.ts',import.meta.url),'utf8');
const output=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const submissionModule={exports:{}};
new Function('exports','module',output)(submissionModule.exports,submissionModule);
const {Submission,ContextReviewRequired,uploadReceiptBinding}=submissionModule.exports;
const body={schema_version:'service.maintenance.v1',operation_id:'operation-1',actor_id:'customer-1',subject_id:'customer-1',organization_id:'business-1',watch_id:'watch-1',expected_revision:0,watch_revision:2,capability_revision:3,policy_revision:1,brand_id:'brand-1',intervention:'limited_maintenance',photo_refs:[],reported_symptoms:'توقف ABC ⌚'};
const requestId='00000000-0000-4000-8000-000000000006';
const photoReference = index => '00000000-0000-4000-8000-' + String(index).padStart(12, '0');
const uploadReceipt = (photo, command, index) => ({...uploadReceiptBinding(photo, command), photo_ref:photoReference(index)});
const reply={...body,state:'submitted',revision:1,request_id:requestId};

test('lost submission response retains operation and acknowledged photo references',async()=>{
  let uploads=0,submits=0;
  const sent=[];
  const transport={upload:async(photo,command)=>{uploads++;return uploadReceipt(photo,command,1);},submit:async data=>{sent.push(data);if(++submits===1)throw new Error('lost_response');return reply;}};
  const submission=new Submission(body,[{operation_id:'photo-1',media_type:'image/png',content_base64:'AAAA'}]);
  const signal=new AbortController().signal;
  await assert.rejects(submission.run(transport,signal));
  assert.equal((await submission.run(transport,signal)).state,'submitted');
  assert.equal(uploads,1);
  assert.equal(submits,2);
  assert.deepEqual(sent[0],sent[1]);
  assert.deepEqual(sent[0].photo_refs,[photoReference(1)]);
});

test('lost upload response retries the original upload reference',async()=>{
  const operations=[];let first=true;
  const transport={upload:async (photo,command)=>{operations.push(photo.operation_id);if(first){first=false;throw new Error('lost_response');}return uploadReceipt(photo,command,1);},submit:async()=>reply};
  const submission=new Submission(body,[{operation_id:'photo-1'}]);
  await assert.rejects(submission.run(transport,new AbortController().signal));
  await submission.run(transport,new AbortController().signal);
  assert.deepEqual(operations,['photo-1','photo-1']);
});

test('malformed upload acknowledgements keep the original keys and block admission', async () => {
  const wrongBindings = Object.keys(uploadReceiptBinding({operation_id:'photo-2'}, body))
    .map(field => ({[field]: field === 'operation_id' ? 'photo-1' : 'unexpected'}));
  for (const invalid of [undefined, null, 6, '', 'invalid', photoReference(2) + '\n', photoReference(1), ...wrongBindings]) {
    const uploads = [];
    const submission = new Submission(body, [{operation_id:'photo-1'}, {operation_id:'photo-2'}]);
    const signal = new AbortController().signal;
    const transport = {
      upload: async (photo, command) => {
        uploads.push(photo.operation_id);
        if (uploads.length === 2) return typeof invalid === 'object' && invalid !== null
          ? {...uploadReceipt(photo,command,2), ...invalid} : {...uploadReceipt(photo,command,2), photo_ref:invalid};
        return uploadReceipt(photo,command,uploads.length === 1 ? 1 : 2);
      },
      submit: async command => {
        assert.deepEqual(command.photo_refs, [photoReference(1), photoReference(2)]);
        assert.equal(command.operation_id, body.operation_id);
        return reply;
      },
    };
    await assert.rejects(submission.run(transport, signal), /response_scope/);
    assert.equal(submission.requestAttempted, false);
    assert.equal(await submission.run(transport, signal), reply);
    assert.deepEqual(uploads, ['photo-1', 'photo-2', 'photo-2']);
  }
});

test('access change prevents upload, submission and late acknowledgement',async()=>{
  const controller=new AbortController();controller.abort();
  let called=false;
  const transport={upload:async()=>{called=true;},submit:async()=>{called=true;}};
  await assert.rejects(new Submission(body,[]).run(transport,controller.signal));
  assert.equal(called,false);
  const active=new AbortController();
  await assert.rejects(new Submission(body,[]).run({...transport,submit:async()=>{active.abort();return reply;}},active.signal));
});

test('cross-account or cross-watch responses cannot become submitted',async()=>{
  for(const change of [{actor_id:'other'},{watch_id:'other'},{organization_id:'other'},{operation_id:'other'}]) {
    await assert.rejects(new Submission(body,[]).run({submit:async()=>({...reply,...change})},new AbortController().signal),/response_scope/);
  }
});

const compile=(file,dependency)=>{
  const code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  const unit={exports:{}};
  new Function('exports','module','require',code)(unit.exports,unit,dependency);
  return unit.exports;
};
const shared=compile(new URL('../../../../packages/i18n/src/index.ts',import.meta.url),()=>({}));
const {dollars}=compile(new URL('../../../../web/features/maintenance/dollars.ts',import.meta.url),name=>{assert.equal(name,'@beirut-time/i18n');return shared;});
test('dollar input preserves exact English and Arabic cents and rejects ambiguous or nonfinite amounts',()=>{
  for(const [input,cents] of [['0',0],['0.01',1],['5000.00',500000],['٥٠٠٠٫٠١',500001],['۵۰۰۰.۰۱',500001],['9999999999.99',999999999999]])assert.equal(dollars(input),cents);
  for(const input of ['1,000','١٬٠٠٠','1.001','-1','Infinity','NaN','1e3','10000000000',''])assert.equal(dollars(input),null);
});

test('pending result can retry the same request without repeating acknowledged uploads',async()=>{
  let uploads=0,submits=0;
  const transport={upload:async(photo,command)=>{uploads++;return uploadReceipt(photo,command,1);},submit:async()=>++submits===1?{...reply,state:'pending',revision:0}:reply};
  const submission=new Submission(body,[{operation_id:'photo-1'}]);
  const signal=new AbortController().signal;
  assert.equal((await submission.run(transport,signal)).state,'pending');
  assert.equal((await submission.run(transport,signal)).state,'submitted');
  assert.equal(uploads,1);
  assert.equal(submits,2);
});

test('private reads use the shared mounted read and withhold denied answers',()=>{
  let answer={data:{revision:1},error:undefined,isPending:false};
  const read={key:['private','account-1']};
  const {usePrivateRead}=compile(new URL('../../../../web/features/maintenance/private-read.ts',import.meta.url),name=>{assert.equal(name,'@/lib/page-speed/read');return {usePageRead:value=>{assert.equal(value,read);return answer;}};});
  assert.equal(usePrivateRead(read).data,answer.data);
  answer={...answer,error:{status:403}};
  assert.equal(usePrivateRead(read).data,undefined);
});

const privateRead = compile(new URL('../../../../web/features/maintenance/private-read.ts', import.meta.url), () => ({}));

const viewSources = new Map();

function viewHarness(file, name, overrides={}, env=process.env) {
  let slots=[],cursor=0,answer,uploads=0;
  const hooks={useCallback(fn){return fn;},useState(initial){const at=cursor++;if(!(at in slots))slots[at]=typeof initial==='function'?initial():initial;return [slots[at],next=>{slots[at]=typeof next==='function'?next(slots[at]):next;}];},useRef(initial){const at=cursor++;return slots[at]??=( {current:initial});},useEffect(effect){effect();},useId(){return 'file';}};
  if (typeof overrides==='function') overrides=overrides(hooks);
  const jsx=(type,props,key)=>({type,props,key});
  const dependencies=specifier=>{
    if(specifier in overrides)return overrides[specifier];
    if(specifier==='react')return hooks;
    if(specifier==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(specifier==='./submission'||specifier==='../submission')return submissionModule.exports;
    if(specifier==='./reads')return {intakeRead:()=>({}),detailRead:()=>({})};
    if(specifier.endsWith('private-read'))return {...privateRead,usePrivateRead:()=>answer};
    if(specifier==='@/lib/page-speed/read')return {usePageRead:()=>answer};
    if(specifier.endsWith('common'))return {useCopy:()=>({t:key=>key,locale:'en'}),useWrite:()=>({}),call:()=>{uploads++;throw new Error('unexpected_upload');},Recovery:'Recovery'};
    if(specifier.endsWith('/definition'))return {definePageRead:()=>()=>({})};
    if(specifier.endsWith('/client'))return {ApiError:class extends Error{}};
    return new Proxy({formatNumber:value=>String(value)},{get:(target,key)=>target[key]??String(key)});
  };
  const cacheKey = JSON.stringify([file, name]);
  let code = viewSources.get(cacheKey);
  if (!code) {
    const source=readFileSync(new URL(file,import.meta.url),'utf8').replace(`export default function ${name}(`,`export function ${name}(`).replace(new RegExp(`(?<!export |export async )function ${name}\\(`),`export function ${name}(`);
    code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
    viewSources.set(cacheKey, code);
  }
  const unit={exports:{}};
  new Function('exports','module','require','process',code)(unit.exports,unit,dependencies,{env});
  return {render(props,read){cursor=0;answer=read;return unit.exports[name](props);},uploads:()=>uploads};
}
function nodes(tree,predicate) {
  if(Array.isArray(tree))return tree.flatMap(item=>nodes(item,predicate));
  if(!tree||typeof tree!=='object')return [];
  return [...(predicate(tree)?[tree]:[]),...nodes(tree.props?.children,predicate)];
}

test('the displayed invalid photo selection replaces prior photos and blocks submission',async()=>{
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm');
  const props={scope:'account',context:{actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,destinations:[{organization_id:'business',interventions:['limited_maintenance']}]}};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  nodes(tree,n=>n.type==='Textarea')[0].props.onValueChange('symptom');
  for(const check of nodes(tree,n=>n.type==='Checkbox'))check.props.onCheckedChange(true);
  const input=()=>nodes(tree,n=>n.type==='input')[0];
  input().props.onChange({target:{files:[{size:10,type:'image/png'}]}});
  tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type==='Button'&&n.props.type==='submit')[0].props.disabled,true);
  nodes(tree,n=>n.type==='Checkbox')[1].props.onCheckedChange(true);
  tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type==='Button'&&n.props.type==='submit')[0].props.disabled,false);
  input().props.onChange({target:{files:[{size:262145,type:'image/png'},{size:10,type:'text/plain'}]}});
  tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type==='Button'&&n.props.type==='submit')[0].props.disabled,true);
  assert.equal(nodes(tree,n=>n.type==='p'&&Array.isArray(n.props.children)&&n.props.children[0]==='selectedFiles')[0].props.children.at(-1),'2');
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  await Promise.resolve();assert.equal(view.uploads(),0);
  input().props.onChange({target:{files:[]}});tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type==='Button'&&n.props.type==='submit')[0].props.disabled,false);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  await Promise.resolve();await Promise.resolve();
  assert.equal(view.uploads(),1);
});

for(const [file,name,data] of [
  ['../../../../web/features/maintenance/intake/index.tsx','Records',{total:1,next_offset:null,items:[{id:'record',order_id:'order',state:'received'}]}],
  ['../../../../web/features/maintenance/intake/evidence.tsx','default',{items:[{id:'evidence',kind:'condition_photo',size:10}]}],
])test(`${name} preserves rows during refresh and transient failure and clears on denial`,()=>{
  const view=viewHarness(file,name);const props={scope:'account',organization:'business',id:'record',revision:1,changed(){},onDenied(){}};
  for(const state of [{data,isPending:false},{data,isPending:true},{data,isPending:false,error:{status:503}}]) {
    const tree=view.render(props,state);
    assert.equal(nodes(tree,n=>n.type==='li').length,1);
    assert.equal(nodes(tree,n=>n.type==='PageLoading').length,0);
    assert.equal(nodes(tree,n=>n.type==='Recovery').length,state.error?1:0);
  }
  const denied=view.render(props,{data:undefined,isPending:false,error:{status:403}});
  assert.equal(nodes(denied,n=>n.type==='li').length,0);
  assert.equal(nodes(denied,n=>n.type==='Recovery').length,1);
});


test('denied intake commands remove the private record subtree before recovery',()=>{
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','Intake');
  const props={scope:'account',organizations:['business']};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  tree=view.render(props);
  const records=nodes(tree,n=>typeof n.type==='function'&&n.type.name==='Records')[0];
  assert.ok(records);
  records.props.onDenied({status:403});
  tree=view.render(props);
  assert.equal(nodes(tree,n=>typeof n.type==='function'&&n.type.name==='Records').length,0);
  nodes(tree,n=>n.type==='Recovery')[0].props.retry();
  tree=view.render(props);
  assert.equal(nodes(tree,n=>typeof n.type==='function'&&n.type.name==='Records').length,0);
  assert.equal(nodes(tree,n=>n.type==='Select')[0].props.value,'');
});

for (const [file, name] of [
  ['../../../../web/features/maintenance/intake/index.tsx', 'Editor'],
  ['../../../../web/features/maintenance/intake/evidence.tsx', 'default'],
]) test(`${name} clears retained private content when the scoped resource is missing`, () => {
  const view = viewHarness(file, name);
  const error = {status: 404};
  let cleared;
  const tree = view.render({scope:'account',organization:'business',id:'record',revision:1,
    onDenied: value => {cleared = value;}}, {
    data:{items:[{id:'private-evidence'}],private_record:{reported_issue:'Private report'}},
    error,
  });
  assert.equal(cleared, error);
  assert.equal(nodes(tree, node => node.type === 'li' || node.type?.name === 'IntakeForm').length, 0);
});

test('the intake photo form confirms a declared upload through the current contract', async () => {
  const previousReader = globalThis.FileReader;
  globalThis.FileReader = class {
    readAsDataURL() {
      this.result = 'data:image/png;base64,AAAA';
      this.onload();
    }
  };
  try {
    const writes = [];
    const id='00000000-0000-4000-8000-000000000002';
    const view = viewHarness('../../../../web/features/maintenance/intake/evidence.tsx','default',hooks=>{
      const common=compile(new URL('../../../../web/features/maintenance/common.tsx',import.meta.url), name=>{
        if(name==='react')return hooks;
        if(name==='./submission')return submissionModule.exports;
        if(name==='@/shell/locale-context')return {useLocale:()=> 'en'};
        if(name==='@/features/identity/session')return {authenticatedRequest:async (path,options)=>{
          writes.push([path,options]);
          return {id:'00000000-0000-4000-8000-000000000003',record_id:id,organization_id:'business',
            operation_id:options.headers['Idempotency-Key'],revision:3};
        }};
        if (name==='./en.json') return JSON.parse(readFileSync(new URL('../../../../web/features/maintenance/en.json',import.meta.url),'utf8'));
        return {};
      });
      return {'../common':common};
    });
    let changed=0;
    const props = {scope:'account',organization:'business',id,revision:2,changed:()=>changed++};
    const read = {data:{items:[]},refetch(){}};
    const find = type => nodes(view.render(props,read),node=>node.type===type)[0];
    find('input').props.onChange({target:{files:[{size:10,type:'image/png'}]}});
    const submit = async () => {
      find('form').props.onSubmit({preventDefault(){}});
      for(let tick=0;tick<6;tick++)await Promise.resolve();
    };
    await submit();
    assert.deepEqual(writes,[]);
    find('Checkbox').props.onCheckedChange(true);
    await submit();
    assert.equal(writes.length,1);
    const [path,options]=writes[0];
    assert.equal(path,`/api/web/v1/service-operations/v1/intake/records/${id}/evidence?organization_id=business`);
    assert.equal(options.method,'POST');
    assert.equal(options.headers['If-Match'],'2');
    assert.deepEqual(JSON.parse(options.body),{
      kind:'condition_photo',safe_photo_declared:true,media_type:'image/png',content_base64:'AAAA',
    });
    assert.equal(changed,1);
    assert.equal(find('Checkbox').props.checked,false);
  } finally {
    globalThis.FileReader = previousReader;
  }
});

test('failed private download recovery repeats the authenticated request',async()=>{
  let calls=0;
  const view=viewHarness('../../../../web/features/maintenance/intake/evidence.tsx','default',{
    '../common':{useCopy:()=>({t:key=>key,locale:'en'}),useWrite:()=>({}),Recovery:'Recovery',call:async()=>{calls++;throw new Error('unavailable');}},
  });
  const props={scope:'account',organization:'business',id:'record',revision:1,changed(){},onDenied(){}};
  const read={data:{items:[{id:'evidence',kind:'condition_photo',size:10}]},isPending:false};
  let tree=view.render(props,read);
  await nodes(tree,n=>n.type==='Button'&&n.props.children==='downloadPrivate')[0].props.onClick();
  await Promise.resolve();
  tree=view.render(props,read);
  assert.equal(calls,1);
  nodes(tree,n=>n.type==='Recovery')[0].props.retry();
  await Promise.resolve();await Promise.resolve();
  assert.equal(calls,2);
});

for(const deniedStatus of [401,403,404]) test(`intake write ${deniedStatus} clears private content and preserves an uncertain reference`,async()=>{
  let slots=[],cursor=0;
  const hooks={useState(initial){const at=cursor++;if(!(at in slots))slots[at]=initial;return [slots[at],next=>{slots[at]=next;}];},useRef(initial){const at=cursor++;return slots[at]??={current:initial};},useEffect(fn){fn();}};
  class ApiError extends Error {constructor(status){super('denied');this.status=status;}}
  let status=deniedStatus,denied;
  const {useWrite}=compile(new URL('../../../../web/features/maintenance/common.tsx',import.meta.url),specifier=>{
    if(specifier==='react')return hooks;
    if(specifier==='@/lib/api/client')return {ApiError};
    if(specifier==='@/features/identity/session')return {authenticatedRequest:async()=>{throw new ApiError(status);}};
    return {};
  });
  const useRender=()=>{cursor=0;return useWrite('account',error=>{denied=error;});};
  await useRender().save('intake/records',{serial:'private'});
  assert.equal(denied.status,deniedStatus);
  assert.equal(useRender().reference,undefined);
  assert.equal(useRender().locked,false);
  status=503;denied=undefined;
  await useRender().save('intake/records',{serial:'private'});
  const reference=useRender().reference;
  assert.ok(reference);
  assert.equal(denied,undefined);
  await useRender().save('intake/records',{serial:'private'});
  assert.equal(useRender().reference,reference);
  status=deniedStatus;
  await useRender().save('intake/records',{serial:'private'});
  assert.equal(denied.status,deniedStatus);
  assert.equal(useRender().reference,reference);
  assert.equal(useRender().locked,true);
});


for(const [file,name] of [
  ['../../../../web/features/maintenance/intake/index.tsx','Records'],
  ['../../../../web/features/maintenance/intake/index.tsx','Editor'],
  ['../../../../web/features/maintenance/intake/evidence.tsx','default'],
])test(`${name} forwards revoked private reads to the clearing boundary`,()=>{
  class ApiError extends Error {constructor(status){super('denied');this.status=status;}}
  const view=viewHarness(file,name,{'@/lib/api/client':{ApiError}});
  for(const status of [401,403,503]) {
    let denied;
    const error=new ApiError(status);
    view.render({scope:'account',organization:'business',id:'record',revision:1,changed(){},onDenied:value=>{denied=value;}},{data:undefined,error,isPending:false});
    assert.equal(denied,status===503?undefined:error);
  }
});


test('request denial removes private context and requires a new authorized read',()=>{
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','WatchRequest');
  const props={scope:'account'};
  const data={actor_id:'customer',watch_id:'watch',destinations:[]};
  let tree=view.render(props,{data,isPending:false});
  nodes(tree,n=>n.type==='Input')[0].props.onValueChange('watch');
  tree=view.render(props,{data,isPending:false});
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  tree=view.render(props,{data,isPending:false});
  const form=nodes(tree,n=>typeof n.type==='function'&&n.type.name==='RequestForm')[0];
  assert.ok(form);
  form.props.onDenied({status:403});
  tree=view.render(props,{data,isPending:false});
  assert.equal(nodes(tree,n=>typeof n.type==='function'&&n.type.name==='RequestForm').length,0);
  assert.equal(nodes(tree,n=>n.type==='Input')[0].props.value,'');
  nodes(tree,n=>n.type==='Recovery')[0].props.retry();
  tree=view.render(props,{data,isPending:false});
  assert.equal(nodes(tree,n=>typeof n.type==='function'&&n.type.name==='RequestForm').length,0);
});

for(const outcome of ['denied',401,403])test(`request submission clears private ownership on ${outcome}`,async()=>{
  class ApiError extends Error {constructor(status){super('denied');this.status=status;}}
  let denied;
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
    '@/lib/api/client':{ApiError},
    './submission':{validPhotos:()=>true,ContextReviewRequired,Submission:class {constructor(body){this.body=body;}async run(){if(typeof outcome==='number')throw new ApiError(outcome);return {state:outcome};}}},
  });
  const props={scope:'account',context:{actor_id:'customer',subject_id:'customer',watch_id:'watch',destinations:[{organization_id:'business',interventions:['limited_maintenance']}]},onDenied:error=>{denied=error;}};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  nodes(tree,n=>n.type==='Textarea')[0].props.onValueChange('private symptom');
  for(const check of nodes(tree,n=>n.type==='Checkbox'))check.props.onCheckedChange(true);
  tree=view.render(props);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  for(let count=0;count<6;count++)await Promise.resolve();
  assert.equal(denied?.status,typeof outcome==='number'?outcome:403);
});

test('conflict resolves the original operation through authenticated lookup',async()=>{
  const submission=new Submission(body,[]);
  let lookedUp;
  const result=await submission.run({
    submit:async()=>{throw {status:409};},
    lookup:async original=>{lookedUp=original;return reply;},
  },new AbortController().signal);
  assert.equal(result.state,'submitted');
  assert.equal(lookedUp.operation_id,body.operation_id);
});

test('unresolved conflict keeps the same operation for another retry',async()=>{
  const submission=new Submission(body,[]);
  const operations=[];
  const transport={
    submit:async original=>{operations.push(original.operation_id);throw {status:409};},
    lookup:async()=>{throw {status:503};},
  };
  for(let index=0;index<2;index++)await assert.rejects(submission.run(transport,new AbortController().signal));
  assert.deepEqual(operations,[body.operation_id]);
});


test('absent operation after conflict requires review; unavailable lookup preserves uncertainty',async()=>{
  for(const status of [404,503]) {
    const submission=new Submission(body,[]);
    for(let attempt=0;attempt<2;attempt++) {
      await assert.rejects(submission.run({submit:async()=>{throw {status:409};},lookup:async()=>{throw {status,code:status===404?'operation_missing':'unavailable'};}},new AbortController().signal),error=>status===404?error instanceof ContextReviewRequired:error.status===503);
      assert.equal(submission.body.operation_id,body.operation_id);
    }
  }
});

test('stale recovery requires current scope review and explicit adoption while keeping the draft',async()=>{
  const submitted=[];let reviews=0;
  const initial={actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,destinations:[{organization_id:'business',display_name:'Synthetic business',brand_id:'brand',capability_revision:1,policy_revision:1,interventions:['limited_maintenance']}]};
  const current={...initial,watch_revision:2,destinations:[{...initial.destinations[0],capability_revision:2}]};
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
    './submission':{validPhotos:()=>true,ContextReviewRequired,Submission:class {constructor(body){this.body=body;submitted.push(body);}revise(body){return new this.constructor(body);}async run(){if(submitted.length===1)throw new ContextReviewRequired();return {state:'submitted'};}}},
  });
  const newest={...current,watch_revision:3,destinations:[{...current.destinations[0],policy_revision:2}]};
  const props={scope:'account',context:initial,onDenied(){},reviewContext:async()=>{
    reviews++;
    return reviews===1?{...current,destinations:[]}:reviews===2?current:newest;
  }};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  const text=nodes(tree,n=>n.type==='Textarea');text[0].props.onValueChange('توقف ABC ⌚');text[1].props.onValueChange('Private draft');
  for(const check of nodes(tree,n=>n.type==='Checkbox'))check.props.onCheckedChange(true);
  const settle=async()=>{for(let count=0;count<8;count++)await Promise.resolve();};
  tree=view.render(props);nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});await settle();
  tree=view.render(props);
  const original=submitted[0].operation_id;
  assert.equal(nodes(tree,n=>n.type==='fieldset')[0].props.disabled,true);
  assert.equal(nodes(tree,n=>n.type==='bdi')[0].props.children,original);
  assert.equal(reviews,0);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='reviewContext')[0].props.onClick();await settle();
  tree=view.render(props);
  assert.equal(reviews,1);assert.equal(submitted.length,1);
  assert.equal(nodes(tree,n=>n.type==='fieldset')[0].props.disabled,true);
  assert.equal(nodes(tree,n=>n.type==='Button'&&n.props.children==='adoptContext')[0].props.disabled,true);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='adoptContext')[0].props.onClick();
  tree=view.render(props);assert.equal(nodes(tree,n=>n.type==='fieldset')[0].props.disabled,true);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='reviewContext')[0].props.onClick();await settle();
  tree=view.render(props);assert.equal(reviews,2);
  assert.equal(nodes(tree,n=>n.type==='Button'&&n.props.children==='adoptContext')[0].props.disabled,false);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='adoptContext')[0].props.onClick();
  tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type==='Textarea')[0].props.value,'توقف ABC ⌚');
  assert.equal(nodes(tree,n=>n.type==='Textarea')[1].props.value,'Private draft');
  assert.equal(nodes(tree,n=>n.type==='Select')[0].props.value,'business');
  assert.equal(nodes(tree,n=>n.type==='fieldset')[0].props.disabled,false);
  assert.equal(nodes(tree,n=>n.type==='Checkbox')[0].props.checked,false);
  nodes(tree,n=>n.type==='Checkbox')[0].props.onCheckedChange(true);
  const refreshed={...props,context:newest};
  tree=view.render(refreshed);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});await settle();
  tree=view.render(refreshed);
  assert.equal(submitted.length,1);
  assert.equal(nodes(tree,n=>n.type==='bdi')[0].props.children,original);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='reviewContext')[0].props.onClick();await settle();
  tree=view.render(refreshed);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='adoptContext')[0].props.onClick();
  tree=view.render(refreshed);
  assert.equal(nodes(tree,n=>n.type==='Checkbox')[0].props.checked,false);
  nodes(tree,n=>n.type==='Checkbox')[0].props.onCheckedChange(true);
  tree=view.render(refreshed);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});await settle();
  assert.equal(submitted.length,2);assert.equal(submitted[1].operation_id,original);
  assert.equal(submitted[1].watch_revision,3);assert.equal(submitted[1].capability_revision,2);
  assert.equal(submitted[1].policy_revision,2);
});


for(const changedBusiness of [false,true])test(`delayed original receipt survives reviewed revisions and business change ${changedBusiness}`,async()=>{
  const reviewed={...body,watch_revision:3,capability_revision:4,policy_revision:2,...(changedBusiness?{organization_id:'business-2'}:{})};
  const submission=new Submission(reviewed,[],[body]);
  const lookups=[];
  const transport={submit:async()=>{throw {status:409};},lookup:async binding=>{lookups.push(binding.organization_id);if(binding.organization_id!==body.organization_id)throw {status:404,code:'operation_missing'};return reply;}};
  assert.equal(await submission.run(transport,new AbortController().signal),reply);
  assert.deepEqual(lookups,changedBusiness?['business-2',body.organization_id]:[body.organization_id]);
  for(const change of [{actor_id:'other'},{watch_id:'other'},{subject_id:'other'},{operation_id:'other'},{policy_revision:999}]) {
    await assert.rejects(submission.run({...transport,lookup:async()=>({...reply,...change})},new AbortController().signal),/response_scope/);
  }
});


test('reviewed scope prepares ten fresh references while retaining the request operation',async()=>{
  let uploads=0;const sent=[];
  const transport={upload:async(photo,command)=>uploadReceipt(photo,command,++uploads),submit:async value=>{sent.push(value);if(sent.length===1)throw {status:409};return {...reply,watch_revision:3};},lookup:async()=>{throw {status:404,code:'operation_missing'};}};
  const photos=Array.from({length:10},(_,i)=>({operation_id:'photo-'+i,media_type:'image/png',content_base64:'AAAA'}));
  const original=new Submission(body,photos);
  await assert.rejects(original.run(transport,new AbortController().signal),ContextReviewRequired);
  const revised=original.revise({...body,watch_revision:3});
  assert.equal((await revised.run(transport,new AbortController().signal)).state,'submitted');
  assert.equal(uploads,20);assert.notDeepEqual(sent[1].photo_refs,sent[0].photo_refs);
  assert.equal(sent[1].operation_id,sent[0].operation_id);
  assert.deepEqual(revised.photos.map(photo=>photo.content_base64),photos.map(photo=>photo.content_base64));
  assert.throws(()=>original.revise({...body,organization_id:'other'}),/response_scope/);
});

test('reviewed photo scope checks for the original receipt before uploading again',async()=>{
  const original=new Submission(body,[{operation_id:'photo-1',media_type:'image/png',content_base64:'AAAA'}]);
  const signal=new AbortController().signal;
  await assert.rejects(original.run({
    upload:async(photo,command)=>uploadReceipt(photo,command,1),
    submit:async()=>{throw new Error('lost_response');},
  },signal),/lost_response/);
  const revised=original.revise({...body,intervention:'overhaul_assessment'});
  assert.equal(await revised.run({
    lookup:async binding=>{assert.equal(binding.operation_id,body.operation_id);return reply;},
    upload:async()=>assert.fail('Committed request must not prepare another photo'),
    submit:async()=>assert.fail('Committed request must not resubmit'),
  },signal),reply);
});

test('business intake opens the assigned-record editor under either shell', () => {
  const editor = () => null;
  for (const foundation of [false, true]) {
    const adapter = viewHarness('../../../../web/features/maintenance/intake/route.tsx', 'IntakeRoute', {
      '@/shell/foundation/path': {usesFoundationShell: () => foundation},
      './index': {default: editor, __esModule: true},
    });
    const page = viewHarness('../../../../web/app/(intake)/business-intake/page.tsx', 'BusinessIntakePage', {
      '@/features/maintenance/intake/route': {default: props => adapter.render(props), __esModule: true},
    });
    const entry = page.render({});
    const intake = entry.type(entry.props);
    assert.equal(intake.type, editor);
    assert.equal(intake.props.screen, 'intake');
    assert.equal(intake.props.mountedRead, !foundation);
  }
});

test('the intake document title follows the current locale', async () => {
  let locale = 'en';
  const page = viewHarness('../../../../web/app/(intake)/business-intake/page.tsx', 'generateMetadata', {
    '@/shell/locale': {getLocale: async () => locale},
  });
  assert.equal((await page.render({})).title.absolute, 'Technical intake · Beirut Time');
  locale = 'ar';
  assert.equal((await page.render({})).title.absolute, 'الاستلام الفني · بيروت تايم');
});

test('the intake delivery declaration owns the current queue read',()=>{
  const declarations=JSON.parse(readFileSync(new URL('../../../../web/features/maintenance/delivery-contract.json',import.meta.url),'utf8'));
  const intake=declarations.find(page=>page.route==='/business-intake');
  assert.deepEqual(Object.keys(intake).sort(),['route','file','view','kind','reason','content','read','proof'].sort());
  assert.equal(intake.file,'web/app/(intake)/business-intake/page.tsx');
  assert.equal(intake.view,'web/features/maintenance/intake/index.tsx');
  assert.equal(intake.kind,'reads');
  assert.equal(intake.read,'maintenance-intake');
  assert.equal(intake.proof,'owed');
  const view=readFileSync(new URL('../../../../'+intake.view,import.meta.url),'utf8');
  assert.match(view,/useRead\(intakeRead\(/);
});

for(const locale of ['en','ar'])test(`intake displays its heading and destination guidance in ${locale}`,()=>{
  const copy=JSON.parse(readFileSync(new URL(`../../../../web/features/maintenance/${locale}.json`,import.meta.url),'utf8'));
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','Intake',{
    '../common':{useCopy:()=>({t:key=>copy[key],locale})},
  });
  const tree=view.render({screen:'intake',scope:'account',organizations:['business']});
  assert.equal(nodes(tree,node=>node.props?.title===copy.intake).length,1);
  assert.equal(nodes(tree,node=>node.props?.lead===copy.scopePolicy).length,1);
  assert.equal(nodes(tree,node=>node.props?.title===copy.chooseOrganization&&node.props?.body===copy.readFirst).length,1);
});

for(const locale of ['en','ar'])test(`maintenance sign-in stays on the request page in ${locale}`,async()=>{
  const copy=JSON.parse(readFileSync(new URL(`../../../../web/features/maintenance/${locale}.json`,import.meta.url),'utf8'));
  let session=null;const calls=[];
  const identity={useSession:()=>session,useSessionState:()=>session?'authenticated':'anonymous',beginSession:async(...args)=>{calls.push(args);if(calls.length===1)throw new Error('lost_response');session={access_fingerprint:'current-access'};}};
  const common={useCopy:()=>({t:key=>copy[key],locale})};
  const boundary=viewHarness('../../../../web/features/maintenance/request.tsx','MaintenanceRequest',{'@/features/identity/session':identity,'./common':common,'./sign-in':{__esModule:true,default:'MaintenanceSignIn'}});
  let tree=boundary.render({});
  assert.equal(nodes(tree,n=>n.type==='MaintenanceSignIn').length,1);
  const form=viewHarness('../../../../web/features/maintenance/sign-in.tsx','MaintenanceSignIn',{'@/features/identity/session':identity,'./common':common});
  tree=form.render({});
  const inputs=nodes(tree,n=>n.type==='Input');
  inputs[0].props.onValueChange('buyer@example.test');inputs[1].props.onValueChange('test-password-1234');
  const send=async()=>{tree=form.render({});nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});for(let i=0;i<6;i++)await Promise.resolve();};
  await send();tree=form.render({});
  assert.equal(nodes(tree,n=>n.props?.role==='alert')[0].props.children,copy.signInFailed);
  assert.equal(nodes(tree,n=>n.type==='Input')[1].props.value,'test-password-1234');
  await send();
  assert.deepEqual(calls[0],calls[1]);
  tree=boundary.render({});
  assert.equal(nodes(tree,n=>typeof n.type==='function'&&n.type.name==='WatchRequest').length,1);
  assert.equal(nodes(tree,n=>n.type==='MaintenanceSignIn').length,0);
});

test('an uncertain request resolves through lookup after the current destination disappears',async()=>{
  const initial={actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,
    destinations:[{organization_id:'business',brand_id:'brand',capability_revision:1,policy_revision:1,interventions:['limited_maintenance']}]};
  const requests=[];
  let original;
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
    './common':{useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      requests.push(path);
      if(path==='maintenance/requests'){original=JSON.parse(options.body);throw new Error('lost_response');}
      assert.ok(path.includes(original.operation_id));
      return {...original,state:'submitted',revision:1,request_id:requestId};
    }},
  });
  const props={scope:'account',context:initial};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  nodes(tree,n=>n.type==='Textarea')[0].props.onValueChange('Private symptoms');
  for(const check of nodes(tree,n=>n.type==='Checkbox'))check.props.onCheckedChange(true);
  const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  tree=view.render(props);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  await settle();
  const refreshed={...props,context:{...initial,destinations:[]}};
  tree=view.render(refreshed);
  assert.equal(nodes(tree,n=>n.type==='bdi')[0].props.children,original.operation_id);
  assert.equal(nodes(tree,n=>n.props?.children==='discardPhotoAttempt').length,0);
  nodes(tree,n=>n.type==='Recovery')[0].props.retry();
  await settle();
  tree=view.render(refreshed);
  assert.equal(requests.length,2);
  assert.match(requests[1],/^maintenance\/operations\//);
  assert.ok(nodes(tree,n=>n.props?.role==='status'&&n.props.children==='requestSubmitted').length);
});

test('a background policy change cannot silently reuse assessment consent',async()=>{
  const destination={organization_id:'business',brand_id:'brand',capability_revision:1,policy_revision:1,interventions:['limited_maintenance']};
  const context={actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,destinations:[destination]};
  const current={...context,destinations:[{...destination,policy_revision:2}]};
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm');
  const props={scope:'account',context,reviewContext:async()=>current};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  nodes(tree,n=>n.type==='Textarea')[0].props.onValueChange('Private symptoms');
  for(const check of nodes(tree,n=>n.type==='Checkbox'))check.props.onCheckedChange(true);
  const refreshed={...props,context:current};
  tree=view.render(refreshed);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  tree=view.render(refreshed);
  assert.equal(view.uploads(),0);
  assert.ok(nodes(tree,n=>n.props?.children==='reviewChangedScope').length);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='reviewContext')[0].props.onClick();
  await Promise.resolve();
  tree=view.render(refreshed);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='adoptContext')[0].props.onClick();
  tree=view.render(refreshed);
  assert.equal(nodes(tree,n=>n.type==='Checkbox')[0].props.checked,false);
  assert.equal(nodes(tree,n=>n.type==='Textarea')[0].props.value,'Private symptoms');
});

test('reconciling a newer intake retains notes and adopts current protected values',async()=>{
  const writes=[];
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeForm',{
    '../common':{useCopy:()=>({t:key=>key,locale:'en'}),useWrite:()=>({save:async(...args)=>writes.push(args)})},
    '../dollars':{dollars:value=>Math.round(Number(value)*100)},
  });
  const privateRecord={currency:'USD',fee_minor:5000,serial:'private',reported_issue:'reported',assessed_issue:'original assessment',accessories:'original accessories',
    diagnostic_opening_permission:true,no_polish_acknowledged:true,fee_acknowledged:true};
  const original={id:'record',order_id:'order',revision:1,custody_receipt_id:null,private_record:privateRecord};
  const props={scope:'account',organization:'business',data:original,saved(){}};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Textarea'&&n.props.label==='reported_issue')[0].props.onValueChange('my note');
  tree=view.render(props);
  nodes(tree,n=>n.type==='Textarea'&&n.props.label==='accessories')[0].props.onValueChange('my accessory note');
  const incoming={...props,data:{...original,revision:2,custody_receipt_id:'current-receipt',custody_verification:'current',
    private_record:{...privateRecord,fee_minor:7000,diagnostic_opening_permission:false,fee_acknowledged:false,assessed_issue:'saved assessment',accessories:'saved accessories'}}};
  tree=view.render(incoming);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  assert.equal(writes.length,0);
  assert.ok(nodes(tree,n=>n.type==='bdi'&&n.props.children==='current-receipt').length);
  assert.equal(nodes(tree,n=>n.type==='dd'&&n.props.children==='no').length,2);
  nodes(tree,n=>n.type==='Button'&&n.props.children==='reconcileConflicts')[0].props.onClick();
  tree=view.render(incoming);
  nodes(tree,n=>n.type==='form')[0].props.onSubmit({preventDefault(){}});
  await Promise.resolve();
  assert.equal(writes[0][2],2);
  assert.equal(writes[0][1].reported_issue,'my note');
  assert.equal(writes[0][1].assessed_issue,'saved assessment');
  assert.equal(writes[0][1].accessories,'saved accessories');
  assert.equal(writes[0][1].custody_receipt_id,'current-receipt');
  assert.equal(writes[0][1].diagnostic_opening_permission,false);
  assert.equal(writes[0][1].fee_acknowledged,false);
  assert.equal(writes[0][1].fee_minor,7000);
});


for (const [locale, fee] of [['en', '50.00'], ['ar', '٥٠٫٠٠']]) {
  test(`intake revision review displays two localized decimal places in ${locale}`, () => {
    const numbers = compile(new URL('../../../../packages/ui/src/foundation/numbers.ts', import.meta.url), () => ({}));
    const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'IntakeForm', {
      '@beirut-time/ui/foundation': {...numbers, Button:'Button', Card:'Card', Input:'Input', Textarea:'Textarea', Checkbox:'Checkbox'},
      '../common': {useCopy:() => ({t:key=>key, locale}), useWrite:()=>({})},
    });
    const props = {scope:'account', organization:'business', data:{
      id:'record', revision:1, private_record:{currency:'USD', fee_minor:100},
    }};
    view.render(props);
    const tree = view.render({...props, data:{...props.data, revision:2,
      private_record:{...props.data.private_record, fee_minor:5000},
    }});
    assert.ok(nodes(tree, node => Array.isArray(node.props?.children) &&
      node.props.children[0] === 'recordedFeeDollars' && node.props.children.includes(fee)).length);
  });
}

for(const locale of ['en','ar'])test(`intake distinguishes current and historical custody in ${locale}`,()=>{
  const copy=JSON.parse(readFileSync(new URL(`../../../../web/features/maintenance/${locale}.json`,import.meta.url),'utf8'));
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','CustodyStatus',{
    '../common':{useCopy:()=>({t:key=>copy[key],locale})},
  });
  let retries=0;
  for(const [verification,message] of [['current','received'],['awaiting_intake','awaiting_intake'],
    ['unconfirmed','custodyUnconfirmed'],['unavailable','custodyUnavailable']]) {
    const tree=view.render({data:{state:'received',custody_verification:verification},refresh:()=>retries++});
    assert.ok(nodes(tree,node=>node.props?.title===copy[message]||node.props?.children===copy[message]).length);
    const [retry]=nodes(tree,node=>node.props?.children===copy.refreshCustody);
    if(retry)retry.props.onClick();
  }
  assert.equal(retries,2);
});

test('an unresolved maintenance operation keeps its watch mounted until recovery',()=>{
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','WatchRequest');
  const props={scope:'account'};
  const read={data:{watch_id:'first',destinations:[]},isPending:false};
  let tree=view.render(props,read);
  const input=()=>nodes(tree,node=>node.type==='Input')[0];
  const open=()=>nodes(tree,node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  const requestForm=()=>nodes(tree,node=>typeof node.type==='function'&&node.type.name==='RequestForm')[0];
  input().props.onValueChange('first');
  tree=view.render(props,read);
  open();
  tree=view.render(props,read);
  assert.equal(requestForm().key,'first');
  requestForm().props.onWatchLockChange(true);
  // A form event already in flight is guarded before the disabled controls render.
  input().props.onValueChange('second');
  tree=view.render(props,read);
  open();
  tree=view.render(props,read);
  assert.equal(input().props.disabled,true);
  assert.equal(requestForm().key,'first');
  requestForm().props.onWatchLockChange(false);
  tree=view.render(props,read);
  assert.equal(input().props.disabled,false);
  open();
  tree=view.render(props,read);
  assert.equal(requestForm().key,'second');
});

test('intake opens a new draft only after the selected business has an assigned queue',()=>{
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','Records');
  const props={scope:'account',organization:'business'};
  const editor=tree=>nodes(tree,node=>typeof node.props?.saved==='function')[0];
  const create=tree=>nodes(tree,node=>node.props?.children==='newRecord'&&node.props?.onClick)[0];
  for (const state of [{isPending:true},{isPending:false,error:{status:503}}]) {
    const tree=view.render(props,state);
    assert.equal(create(tree).props.disabled,true);
    assert.equal(editor(tree),undefined);
  }
  const authorized={data:{total:0,next_offset:null,items:[]},isPending:false};
  create(view.render(props,authorized)).props.onClick();
  assert.equal(editor(view.render(props,authorized)).props.id,'');
  assert.equal(editor(view.render(props,{isPending:true})).props.id,'');
});

test('intake record actions stay on the current editor during an uncertain write',()=>{
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','Records');
  const writes=new Set();
  const props={scope:'account',organization:'business',isLocked:()=>writes.size>0};
  const read={data:{total:2,next_offset:null,items:[
    {id:'first',order_id:'first-order',state:'awaiting_intake'},
    {id:'second',order_id:'second-order',state:'received'},
  ]},isPending:false};
  const button=(tree,label,index=0)=>nodes(tree,node=>node.props?.children===label&&node.props?.onClick)[index];
  const editor=tree=>nodes(tree,node=>node.props?.id!==undefined&&node.props?.saved)[0];
  let tree=view.render(props,read);
  button(tree,'open').props.onClick();
  tree=view.render(props,read);
  const delayedOpen=button(tree,'open',1).props.onClick;
  writes.add('evidence');
  delayedOpen();
  tree=view.render({...props,navigationLocked:true},read);
  assert.equal(editor(tree).props.id,'first');
  assert.equal(button(tree,'newRecord').props.disabled,true);
  assert.equal(button(tree,'open',1).props.disabled,true);
  writes.clear();
  tree=view.render(props,read);
  button(tree,'open',1).props.onClick();
  assert.equal(editor(view.render(props,read)).props.id,'second');
});

for (const status of [401, 403, 404]) test(`watch context ${status} clears the draft and recovers the original operation after access returns`,async()=>{
  class ApiError extends Error {
    constructor(status){super('access');this.status=status;this.code='operation_missing';}
  }
  const paths=[];
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','WatchRequest',{
    '@/lib/api/client':{ApiError},
    './common':{useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',
      SupportLink:'SupportLink',call:async(_scope,path)=>{paths.push(path);if(paths.length===1)throw new ApiError(404);return reply;}},
  });
  const props={scope:'account'};
  const read={data:{watch_id:body.watch_id,destinations:[]},isPending:false};
  let tree=view.render(props,read);
  nodes(tree,node=>node.type==='Input')[0].props.onValueChange(body.watch_id);
  tree=view.render(props,read);
  nodes(tree,node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  tree=view.render(props,read);
  const form=nodes(tree,node=>node.props?.onOperationChange)[0];
  form.props.onWatchLockChange(true);
  form.props.onOperationChange([submissionModule.exports.receiptBinding(body)]);
  const interrupted = view.render(props, {...read, error:new ApiError(503)});
  assert.equal(nodes(interrupted,node=>node.props?.onOperationChange)[0].key,form.key);
  const revoked={...read,error:new ApiError(status)};
  tree=view.render(props,revoked);
  assert.equal(nodes(tree,node=>node.props?.onOperationChange).length,0);
  await Promise.resolve();
  tree=view.render(props,revoked);
  assert.equal(nodes(tree,node=>node.type==='bdi')[0].props.children,body.operation_id);
  nodes(tree,node=>node.type==='Recovery')[0].props.retry();
  await Promise.resolve();
  await Promise.resolve();
  tree=view.render(props,{isPending:false});
  assert.ok(nodes(tree,node=>node.props?.children==='receiptMissing').length);
  assert.ok(nodes(tree,node=>node.type==='SupportLink').length);
  assert.equal(nodes(tree,node=>node.type==='bdi')[0].props.children,body.operation_id);
  nodes(tree,node=>node.props?.children==='retry'&&node.props?.onClick)[0].props.onClick();
  await Promise.resolve();
  await Promise.resolve();
  tree=view.render(props,{isPending:false});
  const expected=`maintenance/operations/${body.operation_id}?organization_id=${body.organization_id}`;
  assert.deepEqual(paths,[expected,expected]);
  assert.ok(nodes(tree,node=>node.props?.children==='requestSubmitted').length);
  assert.equal(nodes(tree,node=>node.type==='Input')[0].props.disabled,false);
});

test('submitted maintenance receipts require revision one on submission and lookup',async()=>{
  for(const revision of [0,2,'1',null]) {
    const transport={submit:async()=>({...reply,revision})};
    const signal=new AbortController().signal;
    await assert.rejects(new Submission(body,[]).run(transport,signal),/response_scope/);
    await assert.rejects(new Submission(body,[]).run({
      submit:async()=>{throw {status:409};},
      lookup:async()=>({...reply,revision}),
    },signal),/response_scope/);
  }
});

test('direct and recovered acknowledgements require a committed request identifier', async () => {
  const signal = new AbortController().signal;
  for (const request_id of [undefined, null, '', 'request-1', requestId + '\n', 6]) {
    const submission = new Submission(body, []);
    const malformed = {...reply, request_id};
    const transport = {submit: async () => malformed, lookup: async () => malformed};
    await assert.rejects(submission.run(transport, signal), /response_scope/);
    assert.equal(submission.requestAttempted, true);
    assert.equal(submission.body.operation_id, body.operation_id);
    assert.equal(await submission.run({
      submit: async () => assert.fail('A committed receipt must resolve the original operation'),
      lookup: async () => reply,
    }, signal), reply);
  }
});

for(const kind of ['save','evidence'])test(`revoked intake ${kind} retains only its receipt binding`,async()=>{
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','Intake');
  const props={scope:'account',organizations:['business']};
  let tree=view.render(props);
  nodes(tree,n=>n.type==='Select')[0].props.onValueChange('business');
  tree=view.render(props);
  const records=nodes(tree,n=>n.type?.name==='Records')[0];
  records.props.lock(kind,true,'test-original-key',requestId,false,3,body.watch_id);
  records.props.onDenied({status:403});
  tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type?.name==='Records').length,0);
  const recovery=nodes(tree,n=>n.type?.name==='IntakeReceiptRecovery')[0];
  assert.deepEqual(recovery.props.binding,{reference:'test-original-key',recordId:requestId,orderId:body.watch_id,expectedRevision:3});
  assert.equal(recovery.props.organization,'business');

  class ApiError extends Error {constructor(status,code='operation_missing'){super('receipt');this.status=status;this.code=code;}}
  const receipt={operation_id:'test-original-key',organization_id:'business',record_id:requestId,order_id:body.watch_id,kind,revision:3};
  const paths=[];
  const recoveryView=viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeReceiptRecovery',{
    '@/lib/api/client':{ApiError},
    '../common':{useCopy:()=>({t:key=>key}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      assert.equal(options.method,'POST');
      assert.deepEqual(JSON.parse(options.body),{action:'lookup',operation_id:'test-original-key'});
      paths.push(path);
      if(paths.length===1)throw new ApiError(404);
      if(paths.length===2)return {...receipt,record_id:'other'};
      if(paths.length===3)return {...receipt,revision:4};
      return receipt;
    }},
  });
  const render=()=>recoveryView.render(recovery.props);
  for(let attempt=1;attempt<=4;attempt++) {
    const button=nodes(render(),n=>n.props?.children==='checkIntakeReceipt'||n.type==='Recovery')[0];
    (button.props.onClick??button.props.retry)();
    for(let i=0;i<6;i++)await Promise.resolve();
    if(attempt<4)assert.equal(nodes(view.render(props),n=>n.type?.name==='IntakeReceiptRecovery').length,1);
  }
  assert.deepEqual(paths,Array(4).fill('intake/records?organization_id=business'));
  tree=view.render(props);
  assert.equal(nodes(tree,n=>n.type?.name==='IntakeReceiptRecovery').length,0);
  assert.equal(nodes(tree,n=>n.props?.role==='status').length,1);
});

test('closing an absent maintenance receipt unblocks a fresh watch only after the scoped acknowledgement',async()=>{
  class ApiError extends Error {constructor(status){super('access');this.status=status;this.code='operation_missing';}}
  const calls=[];
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','WatchRequest',{
    '@/lib/api/client':{ApiError},
    './common':{useCopy:()=>({t:key=>key}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      calls.push([path,options.method]);
      if(options.method==='GET')throw new ApiError(404);
      return {closed:true,operation_id:body.operation_id,organization_id:body.organization_id};
    }},
  });
  const props={scope:'account'};
  const read={data:{watch_id:body.watch_id,destinations:[]},isPending:false};
  let tree=view.render(props,read);
  nodes(tree,node=>node.type==='Input')[0].props.onValueChange(body.watch_id);
  nodes(view.render(props,read),node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  const form=nodes(view.render(props,read),node=>node.props?.onOperationChange)[0];
  form.props.onOperationChange([submissionModule.exports.receiptBinding(body)]);
  form.props.onDenied(new ApiError(403));
  tree=view.render(props,read);
  nodes(tree,node=>node.type==='Recovery')[0].props.retry();
  await Promise.resolve();await Promise.resolve();
  tree=view.render(props,read);
  assert.ok(nodes(tree,node=>node.props?.children==='receiptMissing').length);
  nodes(tree,node=>node.props?.children==='closeUnconfirmed')[0].props.onClick();
  await Promise.resolve();await Promise.resolve();
  tree=view.render(props,read);
  assert.equal(nodes(tree,node=>node.type==='Input')[0].props.value,'');
  assert.deepEqual(calls.map(([,method])=>method),['GET','DELETE']);
  assert.equal(calls[0][0],calls[1][0]);
});

test('watch denial fences the previous context when the same watch is reopened',()=>{
  const reads=[];
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','WatchRequest',{
    '@/lib/page-speed/definition':{definePageRead:spec=>(...args)=>spec.key(...args)},
    '@/lib/page-speed/read':{usePageRead:key=>{
      reads.push(key);
      return key?.[3]===''?{data:{watch_id:'watch',destinations:[]}}:{isPending:true};
    }},
  });
  const props={scope:'account'};
  const open=()=>{
    let tree=view.render(props);
    nodes(tree,node=>node.type==='Input')[0].props.onValueChange('watch');
    tree=view.render(props);
    nodes(tree,node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
    return view.render(props);
  };
  const forms=tree=>nodes(tree,node=>node.props?.onOperationChange);
  forms(open())[0].props.onDenied({status:403});
  assert.equal(forms(open()).length,0);
  assert.equal(reads.at(-1)[2],'watch');
  assert.ok(reads.at(-1)[3]);
});

test('closing an uncommitted intake clears the locked editor after acknowledgement',async()=>{
  class ApiError extends Error {constructor(status,code='operation_missing'){super('receipt');this.status=status;this.code=code;}}
  const owner=viewHarness('../../../../web/features/maintenance/intake/index.tsx','Intake');
  const props={scope:'account',organizations:['business']};
  let tree=owner.render(props);
  nodes(tree,node=>node.type==='Select')[0].props.onValueChange('business');
  tree=owner.render(props);
  const records=nodes(tree,node=>node.type?.name==='Records')[0];
  records.props.lock('save',true,'test-original-key',undefined,false,1,body.watch_id);
  records.props.onDenied(new ApiError(403));
  const recovery=nodes(owner.render(props),node=>node.type?.name==='IntakeReceiptRecovery')[0];
  const calls=[];
  const view=viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeReceiptRecovery',{
    '@/lib/api/client':{ApiError},
    '../common':{useCopy:()=>({t:key=>key}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      assert.equal(path,'intake/records?organization_id=business');
      assert.equal(options.method,'POST');
      const command=JSON.parse(options.body);
      assert.equal(command.operation_id,recovery.props.binding.reference);
      calls.push(command.action);
      if(command.action==='lookup')throw new ApiError(404);
      return {operation_id:recovery.props.binding.reference,organization_id:'business',state:'closed'};
    }},
  });
  const press=async label=>{
    nodes(view.render(recovery.props),node=>node.props?.children===label)[0].props.onClick();
    await Promise.resolve();await Promise.resolve();
  };
  await press('checkIntakeReceipt');
  await press('closeUnconfirmed');
  assert.deepEqual(calls,['lookup','close']);
  tree=owner.render(props);
  assert.equal(nodes(tree,node=>node.type?.name==='IntakeReceiptRecovery').length,0);
  assert.equal(nodes(tree,node=>node.type==='Select')[0].props.value,'');
});

test('a stale request can close the original operation and select a different business', async () => {
  class ApiError extends Error {
    constructor(status) { super('request'); this.status = status; this.code = 'operation_missing'; }
  }
  const original = {organization_id:'business',brand_id:'brand',capability_revision:1,
    policy_revision:1,interventions:['limited_maintenance']};
  const replacement = {...original,organization_id:'replacement'};
  const context = {actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,
    destinations:[original]};
  const calls = [];
  let submitted;
  let closures = 0;
  const view = viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
    '@/lib/api/client':{ApiError},
    './common':{useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      calls.push([path,options.method]);
      if(options.method==='POST'){
        submitted=JSON.parse(options.body);
        const error=new ApiError(409);
        error.code='destination_ineligible';
        throw error;
      }
      if(options.method==='GET')throw new ApiError(404);
      return {closed:true,operation_id:submitted.operation_id,
        organization_id:++closures===1?'wrong-business':submitted.organization_id};
    }},
  });
  const props = {scope:'account',context,reviewContext:async()=>({...context,destinations:[replacement]})};
  const render = () => view.render(props);
  const find = (tree,type) => nodes(tree,node=>node.type===type);
  const press = async label => {
    nodes(render(),node=>node.props?.children===label)[0].props.onClick();
    for(let tick=0;tick<10;tick++)await Promise.resolve();
  };
  find(render(),'Select')[0].props.onValueChange('business');
  find(render(),'Textarea')[0].props.onValueChange('Private symptoms');
  for(const checkbox of find(render(),'Checkbox'))checkbox.props.onCheckedChange(true);
  find(render(),'form')[0].props.onSubmit({preventDefault(){}});
  for(let tick=0;tick<10;tick++)await Promise.resolve();
  await press('reviewContext');
  assert.equal(nodes(render(),node=>node.props?.children==='adoptContext')[0].props.disabled,true);
  await press('checkRequestReceipt');
  await press('closeUnconfirmed');
  assert.equal(find(render(),'bdi')[0].props.children,submitted.operation_id);
  await press('closeUnconfirmed');
  assert.equal(find(render(),'bdi').length,0);
  assert.deepEqual(find(render(),'Select')[0].props.options.map(option=>option.value),['replacement']);
  assert.equal(find(render(),'Textarea')[0].props.value,'Private symptoms');
  assert.equal(find(render(),'Checkbox')[0].props.checked,false);
  assert.deepEqual(calls.slice(1).map(([,method])=>method),['GET','GET','DELETE','DELETE']);
  assert.equal(new Set(calls.slice(1).map(([path])=>path)).size,1);
});

test('a failed custody refresh withholds opening while retaining the private editor', () => {
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx','Editor');
  const props = {scope:'account',organization:'business',id:'record',saved(){},lock(){}};
  const data = {id:'record',revision:2,custody_receipt_id:'receipt',
    custody_verification:'current',diagnosis_allowed:true,private_record:{reported_issue:'Private notes'}};
  const editor = read => nodes(view.render(props,read),node=>node.type?.name==='IntakeForm')[0];
  assert.equal(editor({data}).props.data.diagnosis_allowed,true);
  const retained = editor({data,error:{status:503}}).props.data;
  assert.equal(retained.diagnosis_allowed,false);
  assert.equal(retained.custody_verification,'unavailable');
  assert.equal(retained.custody_receipt_id,'receipt');
  assert.equal(retained.private_record.reported_issue,'Private notes');
  assert.equal(editor({data}).props.data.diagnosis_allowed,true);
});

function assessmentDraft() {
  const first={organization_id:'business',display_name:'First business',interventions:['limited_maintenance','overhaul_assessment']};
  const second={...first,organization_id:'replacement',display_name:'Second business'};
  const context={actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,destinations:[first,second]};
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm');
  const current={...context,destinations:[second]};
  const props={scope:'account',context,reviewContext:async()=>current};
  const control=(type,propsOverride=props)=>nodes(view.render(propsOverride),n=>n.type===type);
  control('Select')[0].props.onValueChange(first.organization_id);
  control('Textarea')[0].props.onValueChange('Private symptoms');
  control('Textarea')[1].props.onValueChange('Private modifications');
  control('input')[0].props.onChange({target:{files:[{size:10,type:'image/png'}]}});
  for(const checkbox of control('Checkbox'))checkbox.props.onCheckedChange(true);
  return {view,props,current,control};
}

test('assessment permission must be renewed after changing business or intervention',()=>{
  const {view,control}=assessmentDraft();
  const submit=()=>control('Button').find(n=>n.props.type==='submit');
  assert.equal(submit().props.disabled,false);
  for(const [field,value] of [['Select','replacement'],['Segmented','overhaul_assessment']]) {
    control(field)[0].props.onValueChange(value);
    assert.equal(control('Checkbox')[0].props.checked,false);
    assert.equal(submit().props.disabled,true);
    control('form')[0].props.onSubmit({preventDefault(){}});
    assert.equal(view.uploads(),0);
    control('Checkbox')[0].props.onCheckedChange(true);
    assert.equal(submit().props.disabled,false);
  }
});

test('withdrawal before admission lets the buyer select a reviewed replacement with the original draft',async()=>{
  const {view,props,current,control}=assessmentDraft();
  const refreshed={...props,context:current};
  const button=label=>control('Button',refreshed).find(n=>n.props.children===label);
  control('form',refreshed)[0].props.onSubmit({preventDefault(){}});
  assert.equal(view.uploads(),0);
  assert.equal(button('checkRequestReceipt'),undefined);
  button('reviewContext').props.onClick();
  await Promise.resolve();
  assert.equal(button('adoptContext').props.disabled,false);
  button('adoptContext').props.onClick();
  const [select]=control('Select',refreshed);
  assert.equal(select.props.value,'');
  assert.deepEqual(select.props.options.map(option=>option.value),['replacement']);
  assert.deepEqual(control('Textarea',refreshed).map(node=>node.props.value),['Private symptoms','Private modifications']);
  assert.ok(nodes(view.render(refreshed),n=>Array.isArray(n.props?.children)&&
    n.props.children[0]==='selectedFiles'&&n.props.children.at(-1)==='1').length);
  select.props.onValueChange('replacement');
  assert.equal(control('Checkbox',refreshed)[0].props.checked,false);
  assert.equal(button('submitRequest').props.disabled,true);
});

test('at the scope review limit the original operation can still be checked and closed', async () => {
  class ApiError extends Error {
    constructor(status) { super('request'); this.status = status; this.code = 'operation_missing'; }
  }
  const destination = {organization_id:'business',brand_id:'brand',capability_revision:1,
    policy_revision:1,interventions:['limited_maintenance']};
  const context = {actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,
    destinations:[destination]};
  let original;
  const calls = [];
  const view = viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
    '@/lib/api/client':{ApiError},
    './submission':{
      ...submissionModule.exports,
      Submission:class extends Submission {
        constructor(command, photos) {
          super(command, photos, Array(99).fill(command));
          original = command;
        }
      },
    },
    './common':{useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      calls.push([path,options.method]);
      if(options.method==='POST')throw new ApiError(409);
      if(options.method==='GET')throw new ApiError(404);
      return {closed:true,operation_id:original.operation_id,organization_id:original.organization_id};
    }},
  });
  const props = {scope:'account',context,reviewContext:async()=>({...context,watch_revision:2})};
  const find = predicate => nodes(view.render(props),predicate);
  const press = async label => {
    find(node=>node.props?.children===label)[0].props.onClick();
    for(let tick=0;tick<10;tick++)await Promise.resolve();
  };
  find(node=>node.type==='Select')[0].props.onValueChange('business');
  find(node=>node.type==='Textarea')[0].props.onValueChange('Private symptoms');
  for(const checkbox of find(node=>node.type==='Checkbox'))checkbox.props.onCheckedChange(true);
  find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  for(let tick=0;tick<10;tick++)await Promise.resolve();
  await press('reviewContext');
  assert.equal(find(node=>node.props?.children==='adoptContext')[0].props.disabled,true);
  assert.ok(find(node=>node.props?.children==='reviewLimitReached').length);
  assert.equal(find(node=>node.type==='bdi')[0].props.children,original.operation_id);
  await press('checkRequestReceipt');
  await press('closeUnconfirmed');
  assert.equal(find(node=>node.type==='bdi').length,0);
  assert.equal(find(node=>node.type==='Textarea')[0].props.value,'Private symptoms');
  assert.deepEqual(calls.map(([,method])=>method),['POST','GET','GET','DELETE']);
  assert.equal(new Set(calls.slice(1).map(([path])=>path)).size,1);
});

test('intake records the offered opening acceptance only after explicit review', async () => {
  const writes = [];
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeForm',{
    '../common':{useCopy:()=>({t:key=>key,locale:'en'}),useWrite:()=>({
      save:async(_path,body,revision)=>writes.push({body,revision}),
    })},
    '../dollars':{dollars:value=>Math.round(Number(value)*100)},
  });
  const former = {quote_id:'quote',quote_revision:1,accepted_terms_revision:1,consent_revision:1};
  const current = {...former,accepted_terms_revision:2};
  const props = {scope:'account',organization:'business',saved(){},data:{
    id:'record',order_id:'order',revision:3,custody_receipt_id:'receipt',custody_verification:'current',
    current_opening_acceptance:current,current_opening_fee_minor:5000,diagnosis_allowed:false,
    private_record:{currency:'USD',fee_minor:5000,opening_acceptance:former},
  }};
  const find = predicate => nodes(view.render(props),predicate);
  const save = () => find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  save();
  assert.deepEqual(writes[0].body.opening_acceptance,former);
  find(node=>node.props?.children==='recordOpeningAcceptance')[0].props.onClick();
  save();
  assert.deepEqual(writes[1].body.opening_acceptance,current);
  assert.equal(writes[1].body.fee_minor,5000);
  assert.equal(writes[1].body.diagnostic_opening_permission,true);
  assert.equal(writes[1].revision,3);
  find(node=>node.props?.label==='reported_issue')[0].props.onValueChange('Unsent observation');
  const withdrawn = {...props, data:{...props.data, current_opening_acceptance:undefined,
    current_opening_fee_minor:undefined}};
  const afterWithdrawal = () => view.render(withdrawn);
  nodes(afterWithdrawal(), node=>node.props?.children==='discardOpeningReview')[0].props.onClick();
  nodes(afterWithdrawal(), node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  assert.deepEqual(writes[2].body.opening_acceptance,former);
  assert.equal(writes[2].body.reported_issue,'Unsent observation');
});

test('mounted intake exposes recovery for an uncertain save and reopens the confirmed record', async () => {
  class ApiError extends Error {
    constructor(status, code) { super(code); this.status = status; this.code = code; }
  }
  const owner = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'Intake');
  const props = {scope:'account', organizations:['business']};
  const ownerNodes = predicate => nodes(owner.render(props), predicate);
  ownerNodes(node=>node.type==='Select')[0].props.onValueChange('business');
  const lock = ownerNodes(node=>node.type?.name==='Records')[0].props.lock;
  lock('save',true,'test-mounted-save',requestId,false,2,body.watch_id);
  assert.equal(ownerNodes(node=>node.type?.name==='IntakeReceiptRecovery').length,0);
  lock('save',true,'test-mounted-save',requestId,true,2,body.watch_id);
  const recovery = ownerNodes(node=>node.type?.name==='IntakeReceiptRecovery')[0];
  assert.equal(recovery.props.binding.reference,'test-mounted-save');
  assert.ok(ownerNodes(node=>node.type?.name==='Records').length);
  const calls = [];
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeReceiptRecovery',{
    '@/lib/api/client':{ApiError},
    '../common':{useCopy:()=>({t:key=>key}),Recovery:'Recovery',call:async(_scope,path,options)=>{
      calls.push([path,options.method,JSON.parse(options.body)]);
      if(calls.length===1)throw new ApiError(404,'not_found');
      return {operation_id:'test-mounted-save',organization_id:'business',record_id:requestId,order_id:body.watch_id,kind:'save',revision:2};
    }},
  });
  const find = predicate => nodes(view.render(recovery.props),predicate);
  find(node=>node.props?.children==='checkIntakeReceipt')[0].props.onClick();
  await Promise.resolve();await Promise.resolve();
  assert.equal(find(node=>node.props?.children==='closeUnconfirmed').length,0);
  find(node=>node.type==='Recovery')[0].props.retry();
  await Promise.resolve();await Promise.resolve();
  assert.equal(ownerNodes(node=>node.type?.name==='IntakeReceiptRecovery').length,0);
  assert.equal(ownerNodes(node=>node.type?.name==='Records')[0].props.initialId,requestId);
  assert.deepEqual(calls,Array(2).fill(['intake/records?organization_id=business','POST',{action:'lookup',operation_id:'test-mounted-save'}]));
});

test('an unregistered maintenance lookup cannot enter scope review', async () => {
  const submission = new Submission(body,[]);
  const gatewayError = {status:404,code:'not_found'};
  await assert.rejects(submission.run({
    submit:async()=>{throw {status:409};},
    lookup:async()=>{throw gatewayError;},
  },new AbortController().signal),error=>error===gatewayError);
});

test('assigned queue and receipt recovery use the existing intake registration', async () => {
  const registration = compile(new URL('../../../../web/registrations/L09.ts',import.meta.url),
    () => ({})).default;
  const path = '/v1/intake/records';
  const query = '?organization_id=business';
  const operation_id = 'test-forwarded-key';
  const committed = {operation_id:'test-committed-key',organization_id:'business',
    record_id:requestId,order_id:body.watch_id,revision:3,kind:'evidence'};
  const calls = [];
  const dependencies = new Map([
    ['identity',{request:async()=>Response.json({actor:{subject_id:'staff'},roles:['dealer']})}],
    ['service-operations',{request:async(method,target,_id,{headers,body})=>{
      const command = body ? JSON.parse(new TextDecoder().decode(body)) : undefined;
      calls.push([method,target,headers.get('Authorization'),command]);
      if (method === 'GET') return Response.json({intake_contract:'current',items:[],total:0,next_offset:null});
      if (command.operation_id===committed.operation_id) return Response.json(committed);
      return command.action==='lookup'
        ? Response.json({error:{code:'operation_missing'}},{status:404})
        : Response.json({operation_id,organization_id:'business',state:'closed'});
    }}],
  ]);
  const {forward} = compile(new URL('../../../../web/gateway/forward.ts',import.meta.url),name=>({
    '@/registry-loader':{gatewayRegistrations:registration.gateway},
    '@/lib/bff/status':{dependencies,serviceNames:['service-operations'],requestId:()=> 'test-request',privateHeaders:()=>({})},
    './origin':{validatedBrowserOrigin:request=>request.headers.get('Origin')},
  })[name]);
  const send = (action, reference=operation_id) => forward(new Request('https://example.test/api/web/v1/service-operations'+path+query,{
    method:'POST',headers:{Authorization:'Bearer test-staff',Origin:'https://example.test','Content-Type':'application/json'},
    body:JSON.stringify({action,operation_id:reference}),
  }),{params:Promise.resolve({service:'service-operations',path:path.slice(1).split('/')})});

  for (const action of ['lookup','close']) {
    const recovered = await send(action,committed.operation_id);
    assert.equal(recovered.status,200);
    assert.deepEqual(await recovered.json(),committed);
  }
  const missing = await send('lookup');
  assert.equal(missing.status,404);
  assert.equal((await missing.json()).error.code,'operation_missing');
  const closed = await send('close');
  assert.equal(closed.status,200);
  assert.deepEqual(await closed.json(),{operation_id,organization_id:'business',state:'closed'});
  const probe = token => forward(new Request('https://example.test/api/web/v1/service-operations'+path+query,{
    headers:token ? {Authorization:token} : {},
  }),{params:Promise.resolve({service:'service-operations',path:path.slice(1).split('/')})});
  assert.equal((await probe()).status,401);
  const contract = await probe('Bearer test-staff');
  assert.equal(contract.status,200);
  assert.deepEqual(await contract.json(),{intake_contract:'current',items:[],total:0,next_offset:null});
  assert.deepEqual(calls,[
    ...[committed.operation_id,operation_id].flatMap(reference=>['lookup','close'].map(action=>
      ['POST',path+query,'Bearer test-staff',{action,operation_id:reference}])),
    ['GET',path+query,'Bearer test-staff',undefined],
  ]);
});

test('a malformed or unavailable photo acknowledgement can retry its original key or unlock the draft', async () => {
  const previousReader = globalThis.FileReader;
  globalThis.FileReader = class {
    readAsDataURL() {
      this.result = 'data:image/png;base64,AAAA';
      this.onload();
    }
  };
  try {
    const operations = [];
    const locks = [];
    const view = viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
      './common': {useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',
        call:async(_scope,path,options)=>{
          assert.equal(path,'maintenance/photos');
          operations.push(JSON.parse(options.body));
          if (operations.length === 1) return {};
          throw new Error('unavailable');
        }},
    });
    const props = {scope:'account',onWatchLockChange:value=>locks.push(value),
      context:{actor_id:'buyer',subject_id:'buyer',watch_id:'watch',watch_revision:1,
        destinations:[{organization_id:'business',brand_id:'brand',capability_revision:2,policy_revision:3,interventions:['limited_maintenance']}]}};
    const find = predicate => nodes(view.render(props),predicate);
    find(node=>node.type==='Select')[0].props.onValueChange('business');
    find(node=>node.type==='Textarea')[0].props.onValueChange('Private symptom');
    find(node=>node.type==='input')[0].props.onChange({target:{files:[{size:10,type:'image/png'}]}});
    for(const checkbox of find(node=>node.type==='Checkbox'))checkbox.props.onCheckedChange(true);
    find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
    const settle = async()=>{for(let tick=0;tick<14;tick++)await Promise.resolve();};
    await settle();
    find(node=>node.type==='Recovery')[0].props.retry();
    await settle();
    assert.deepEqual(operations[0],operations[1]);
    const {brand_id, intervention, watch_revision, capability_revision, policy_revision} = operations[0];
    assert.deepEqual({brand_id, intervention, watch_revision, capability_revision, policy_revision}, {
      brand_id:'brand', intervention:'limited_maintenance', watch_revision:1,
      capability_revision:2, policy_revision:3,
    });
    assert.equal(operations.length,2);
    find(node=>node.props?.children==='discardPhotoAttempt')[0].props.onClick();
    assert.equal(locks.at(-1),false);
    assert.equal(find(node=>node.type==='fieldset')[0].props.disabled,false);
    assert.equal(find(node=>node.type==='bdi').length,0);
    assert.equal(find(node=>node.type==='Textarea')[0].props.value,'Private symptom');
    assert.equal(find(node=>node.props?.children==='discardPhotoAttempt').length,0);
    find(node=>node.type==='input')[0].props.onChange({target:{files:[{size:12,type:'image/png'}]}});
    find(node=>node.type==='Checkbox')[1].props.onCheckedChange(true);
    find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
    await settle();
    assert.equal(operations.length,3);
    assert.notEqual(operations[2].operation_id,operations[0].operation_id);
    assert.notEqual(operations[2].request_operation_id,operations[0].request_operation_id);
  } finally {
    globalThis.FileReader = previousReader;
  }
});

test('a reviewed overhaul can recover an earlier limited maintenance receipt', async () => {
  const revised={...body,intervention:'overhaul_assessment',policy_revision:2};
  const submission=new Submission(revised,[],[body]);
  const transport={submit:async()=>{throw {status:409};},lookup:async()=>reply};
  const signal=new AbortController().signal;
  const receipt=await submission.run(transport,signal);
  assert.equal(receipt.intervention,'limited_maintenance');
  for(const change of [{intervention:'overhaul_assessment'},{brand_id:'other-brand'}]) {
    await assert.rejects(submission.run({...transport,lookup:async()=>({...reply,...change})},signal),/response_scope/);
  }
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','SubmittedScope');
  const shown=nodes(view.render({receipt}),node=>node.type==='dd').map(node=>node.props.children);
  assert.equal(shown.at(-1),'limited');
});

test('ordinary admission timeout can close a scoped missing receipt and unlock the draft', async () => {
  class ApiError extends Error {
    constructor(status,code) { super(code); this.status=status; this.code=code; }
  }
  const calls=[];
  let original;
  const locks=[];
  const view=viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
    '@/lib/api/client':{ApiError},
    './common':{useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',SupportLink:'SupportLink',call:async(_scope,path,options)=>{
      calls.push([path,options.method]);
      if(options.method==='POST'){
        const command=JSON.parse(options.body);
        original??=command;
        assert.deepEqual(command,original);
        throw new ApiError(503,'unavailable');
      }
      if(options.method==='GET')throw new ApiError(404,'operation_missing');
      return {closed:true,operation_id:original.operation_id,organization_id:original.organization_id};
    }},
  });
  const props={scope:'account',onWatchLockChange:locked=>locks.push(locked),context:{
    actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,
    destinations:[{organization_id:'business',brand_id:'brand',capability_revision:1,
      policy_revision:1,interventions:['limited_maintenance']}],
  }};
  let context=props.context;
  const find=predicate=>nodes(view.render({...props,context}),predicate);
  const label=name=>find(node=>node.props?.children===name);
  const settle=async()=>{for(let i=0;i<14;i++)await Promise.resolve();};
  find(node=>node.type==='Select')[0].props.onValueChange('business');
  find(node=>node.type==='Textarea')[0].props.onValueChange('Private symptoms');
  for(const checkbox of find(node=>node.type==='Checkbox'))checkbox.props.onCheckedChange(true);
  find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  await settle();
  find(node=>node.type==='Recovery')[0].props.retry();
  await settle();
  assert.equal(label('reviewContext').length,0);
  assert.equal(label('closeUnconfirmed').length,0);
  label('checkRequestReceipt')[0].props.onClick();
  await settle();
  assert.equal(find(node=>node.type==='bdi')[0].props.children,original.operation_id);
  assert.ok(find(node=>node.type==='SupportLink').length);
  context={...context,destinations:[]};
  label('closeUnconfirmed')[0].props.onClick();
  await settle();
  assert.deepEqual(calls.map(([,method])=>method),['POST','GET','POST','GET','DELETE']);
  assert.equal(new Set(calls.filter(([,method])=>method!=='POST').map(([path])=>path)).size,1);
  assert.match(calls.at(-1)[0],new RegExp(original.operation_id));
  assert.equal(locks.at(-1),false);
  assert.equal(find(node=>node.type==='fieldset')[0].props.disabled,false);
  assert.equal(find(node=>node.type==='Textarea')[0].props.value,'Private symptoms');
  const select=()=>find(node=>node.type==='Select')[0];
  assert.deepEqual(select().props.options,[]);
  context={...context,destinations:[
    {...props.context.destinations[0], organization_id:'replacement', display_name:'Eligible business'},
  ]};
  assert.deepEqual(select().props.options.map(option=>option.value),['replacement']);
  select().props.onValueChange('replacement');
  assert.equal(find(node=>node.type==='Textarea')[0].props.value,'Private symptoms');
  assert.equal(find(node=>node.type==='Checkbox')[0].props.checked,false);
  find(node=>node.type==='Checkbox')[0].props.onCheckedChange(true);
  assert.equal(find(node=>node.props?.type==='submit')[0].props.disabled,false);
});

test('a rejected resubmission keeps the original uncertain request until closure', async () => {
  class ApiError extends Error {
    constructor(status, code) { super(code); this.status = status; this.code = code; }
  }
  let original;
  const calls = [];
  const locks = [];
  const view = viewHarness('../../../../web/features/maintenance/request.tsx', 'RequestForm', {
    '@/lib/api/client': {ApiError},
    './common': {useCopy:()=>({t:key=>key,locale:'en'}),Recovery:'Recovery',
      call:async(_scope,path,options)=>{
        calls.push(options.method);
        if(options.method==='POST'){
          const command=JSON.parse(options.body);
          original??=command;
          assert.deepEqual(command,original);
          throw calls.length===1?new ApiError(503,'unavailable'):new ApiError(422,'invalid');
        }
        assert.match(path,new RegExp(original.operation_id));
        if(options.method==='GET')throw new ApiError(404,'operation_missing');
        return {closed:true,operation_id:original.operation_id,organization_id:original.organization_id};
      }},
  });
  const props={scope:'account',onWatchLockChange:locked=>locks.push(locked),context:{
    actor_id:'customer',subject_id:'customer',watch_id:'watch',watch_revision:1,
    destinations:[{organization_id:'business',brand_id:'brand',capability_revision:1,
      policy_revision:1,interventions:['limited_maintenance']}],
  }};
  const find=predicate=>nodes(view.render(props),predicate);
  const press=label=>find(node=>node.props?.children===label)[0].props.onClick();
  const settle=async()=>{for(let tick=0;tick<14;tick++)await Promise.resolve();};
  find(node=>node.type==='Select')[0].props.onValueChange('business');
  find(node=>node.type==='Textarea')[0].props.onValueChange('Private symptoms');
  for(const checkbox of find(node=>node.type==='Checkbox'))checkbox.props.onCheckedChange(true);
  find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
  await settle();
  find(node=>node.type==='Recovery')[0].props.retry();
  await settle();
  assert.equal(find(node=>node.type==='bdi')[0].props.children,original.operation_id);
  assert.equal(find(node=>node.type==='fieldset')[0].props.disabled,true);
  assert.equal(locks.at(-1),true);
  press('checkRequestReceipt');
  await settle();
  press('closeUnconfirmed');
  await settle();
  assert.deepEqual(calls,['POST','GET','POST','GET','DELETE']);
  assert.equal(find(node=>node.type==='bdi').length,0);
  assert.equal(locks.at(-1),false);
});

for (const locale of ['en', 'ar']) {
  test(`an empty eligible-business refresh preserves the draft in ${locale}`, () => {
    const copy = JSON.parse(readFileSync(new URL(`../../../../web/features/maintenance/${locale}.json`, import.meta.url), 'utf8'));
    const view = viewHarness('../../../../web/features/maintenance/request.tsx', 'RequestForm', {
      './common': {useCopy: () => ({t: key => copy[key], locale})},
    });
    let refreshes = 0;
    const props = {scope: 'account', context: {destinations: []}, refreshContext: () => refreshes++};
    const symptoms = tree => nodes(tree, node => node.props?.label === copy.symptoms)[0];
    symptoms(view.render(props)).props.onValueChange('توقف ABC ⌚');

    const empty = view.render(props);
    assert.ok(nodes(empty, node => node.props?.title === copy.emptyDestinations &&
      node.props?.body === copy.noCurrentDestinations).length);
    nodes(empty, node => node.props?.children === copy.refreshDestinations)[0].props.onClick();
    assert.equal(refreshes, 1);
    const failed = view.render({...props, contextUnavailable: true});
    assert.equal(nodes(failed, node => node.props?.title === copy.emptyDestinations).length, 0);
    assert.equal(symptoms(failed).props.value, 'توقف ABC ⌚');
    const refreshed = view.render({...props, context: {...props.context, destinations: [
      {organization_id:'business', display_name:'Eligible business', interventions:['limited_maintenance']},
    ]}});
    const selector = nodes(refreshed, node => node.type === 'Select')[0];
    assert.deepEqual(selector.props.options.map(option => option.value), ['business']);
    assert.equal(symptoms(refreshed).props.value, 'توقف ABC ⌚');
  });
}

for (const status of [401, 403]) {
  test(`intake receipt recovery clears the private editor on ${status}`, async () => {
    class ApiError extends Error {
      constructor() { super('access'); this.status = status; }
    }
    const owner = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'Intake');
    const props = {scope:'account', organizations:['business']};
    const find = predicate => nodes(owner.render(props), predicate);
    find(node => node.type === 'Select')[0].props.onValueChange('business');
    find(node => node.type?.name === 'Records')[0].props.lock('evidence',true,'test-original-upload','record',true,2,body.watch_id);
    const recovery = () => find(node => node.type?.name === 'IntakeReceiptRecovery')[0];
    const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeReceiptRecovery',{
      '@/lib/api/client':{ApiError},
      '../common':{useCopy:()=>({t:key=>key}),Recovery:'Recovery',call:async()=>{throw new ApiError();}},
    });
    nodes(view.render(recovery().props),node=>node.props?.children==='checkIntakeReceipt')[0].props.onClick();
    for(let tick=0;tick<6;tick++)await Promise.resolve();
    assert.equal(find(node=>node.type?.name==='Records').length,0);
    assert.equal(recovery().props.binding.reference,'test-original-upload');
  });
}

test('replacing intake photos requires a fresh declaration and successful upload clears it', async () => {
  const previousReader = globalThis.FileReader;
  globalThis.FileReader = class {
    readAsDataURL() {
      this.result = 'data:image/png;base64,AAAA';
      this.onload();
    }
  };
  try {
    const uploads = [];
    const view = viewHarness('../../../../web/features/maintenance/intake/evidence.tsx', 'default', {
      '../common': {
        useCopy: () => ({t: key => key, locale: 'en'}),
        useWrite: () => ({save: async (...args) => { uploads.push(args); return {revision: 2}; }}),
      },
    });
    const props = {scope: 'account', organization: 'business', id: 'record', revision: 1, changed() {}};
    const read = {data: {items: []}, refetch() {}};
    const find = type => nodes(view.render(props, read), node => node.type === type)[0];
    const select = size => find('input').props.onChange({target: {files: [{type: 'image/png', size}]}});
    const submit = async () => {
      find('form').props.onSubmit({preventDefault() {}});
      for (let tick = 0; tick < 6; tick++) await Promise.resolve();
    };

    select(10);
    find('Checkbox').props.onCheckedChange(true);
    select(11);
    assert.equal(find('Checkbox').props.checked, false);
    await submit();
    assert.equal(uploads.length, 0);

    find('Checkbox').props.onCheckedChange(true);
    await submit();
    assert.equal(uploads.length, 1);
    assert.equal(find('Checkbox').props.checked, false);
  } finally {
    globalThis.FileReader = previousReader;
  }
});

test('replacing buyer photos with another valid selection clears the declaration', () => {
  const {view, control} = assessmentDraft();
  assert.equal(control('Checkbox')[1].props.checked, true);
  control('input')[0].props.onChange({target: {files: [{size: 12, type: 'image/png'}]}});
  assert.equal(control('Checkbox')[1].props.checked, false);
  assert.equal(control('Button').find(node => node.props.type === 'submit').props.disabled, true);
  control('form')[0].props.onSubmit({preventDefault() {}});
  assert.equal(view.uploads(), 0);
  control('Checkbox')[1].props.onCheckedChange(true);
  assert.equal(control('Button').find(node => node.props.type === 'submit').props.disabled, false);
});

for (const locale of ['en', 'ar']) {
  test(`support opens the localized transaction destination without private data in ${locale}`, () => {
    const copy = JSON.parse(readFileSync(new URL(`../../../../web/features/maintenance/${locale}.json`, import.meta.url), 'utf8'));
    const link = viewHarness('../../../../web/features/maintenance/common.tsx', 'SupportLink', {
      '@/shell/locale-context': {useLocale: () => locale},
      './en.json': copy,
      './ar.json': copy,
    }).render({});
    assert.equal(link.props.href, `/${locale}/inbox`);
    assert.equal(link.props.target, '_blank');
    assert.ok(link.props.rel.includes('noreferrer'));
    assert.ok(nodes(link, node => node.props?.children === copy.openSupport).length);
  });
}

for (const action of ['onRecovered', 'onClosed']) {
  test(`acknowledged evidence recovery preserves the mounted intake draft through ${action}`, async () => {
    const owner = viewHarness('../../../../web/features/maintenance/intake/index.tsx','Intake');
    const props = {scope:'account', organizations:['business']};
    const pick = (tree, name) => nodes(tree, node => node.type?.name === name)[0];
    const render = () => owner.render(props);
    nodes(render(), node => node.type === 'Select')[0].props.onValueChange('business');
    const before = pick(render(), 'Records');
    before.props.lock('evidence', true, 'test-evidence-recovery', 'record', true, 2,body.watch_id);
    const recovery = pick(render(), 'IntakeReceiptRecovery');
    recovery.props[action]({record_id:'record', kind:'evidence', revision:2});
    const after = pick(render(), 'Records');
    assert.equal(after.key, before.key);
    assert.equal(after.props.readGeneration, before.props.readGeneration);
    assert.equal(after.props.navigationLocked, false);
    const attached = action === 'onRecovered';
    assert.deepEqual(after.props.evidenceRefresh, attached ? {recordId:'record',reference:'test-evidence-recovery'} : undefined);
    assert.equal(after.props.closedEvidence, attached ? undefined : 'test-evidence-recovery');

    const editor = viewHarness('../../../../web/features/maintenance/intake/index.tsx','Editor');
    const form = viewHarness('../../../../web/features/maintenance/intake/index.tsx','IntakeForm');
    const original = {id:'record', revision:1, private_record:{currency:'USD', fee_minor:0, reported_issue:'Saved'}};
    const editorProps = {scope:'account', organization:'business', id:'record'};
    let refreshes = 0;
    const refetch = () => refreshes++;
    const draft = tree => nodes(tree, node => node.props?.label === 'reported_issue')[0];
    const first = editor.render(editorProps, {data:original, refetch});
    draft(form.render(pick(first,'IntakeForm').props)).props.onValueChange('Unsent notes');
    const refreshed = editor.render({...editorProps,evidenceRefresh:after.props.evidenceRefresh?.reference,closedEvidence:after.props.closedEvidence},
      {data:{...original, revision:attached ? 2 : 1}, refetch});
    assert.equal(refreshes, attached ? 1 : 0);
    assert.equal(pick(refreshed,'IntakeForm').key, pick(first,'IntakeForm').key);
    const reconciled = pick(refreshed,'IntakeForm').props;
    if(attached)nodes(form.render(reconciled), node => node.props?.children === 'reconcileIntake')[0].props.onClick();
    assert.equal(draft(form.render(reconciled)).props.value,'Unsent notes');
    const panel = tree => nodes(tree, node => node.props?.changed && node.props?.revision)[0];
    assert.equal(panel(refreshed).key, attached ? 'test-evidence-recovery' : panel(first).key);
    assert.equal(panel(refreshed).props.closedReference, after.props.closedEvidence);
  });
}

test('closing an unconfirmed upload preserves the selected photo and declaration for the next attempt', async () => {
  const sent = [];
  let closed;
  const view = viewHarness('../../../../web/features/maintenance/intake/evidence.tsx', 'default', {
    '../common': {
      useCopy: () => ({t:key=>key, locale:'en'}),
      useWrite: (_scope, _denied, _lock, reference) => {
        const operation = 'test-evidence-close';
        const closing = reference === operation && closed !== operation;
        if (reference) closed = reference;
        return {
          reference: sent.length && (!closed || closing) ? operation : undefined,
          save: async (...args) => {sent.push(args);},
        };
      },
      Recovery: 'Recovery',
    },
  });
  const originalReader = globalThis.FileReader;
  globalThis.FileReader = class {
    readAsDataURL(file) {
      this.result = file.data;
      this.onload();
    }
  };
  try {
    const props = {scope:'account', organization:'business', id:'record', revision:1};
    const read = {data:{items:[]}};
    const fields = (tree, type) => nodes(tree, node => node.type === type)[0];
    const photo = {size:4, type:'image/png', data:'data:image/png;base64,AAAA'};
    fields(view.render(props,read),'input').props.onChange({target:{files:[photo]}});
    fields(view.render(props,read),'Checkbox').props.onCheckedChange(true);
    const submit = async tree => {
      fields(tree,'form').props.onSubmit({preventDefault() {}});
      await Promise.resolve();
      await Promise.resolve();
    };
    await submit(view.render(props,read));
    const afterClosure = view.render({...props,revision:2,closedReference:'test-evidence-close'},read);
    assert.equal(fields(afterClosure,'Checkbox').props.checked,true);
    assert.equal(fields(afterClosure,'Button').props.disabled,false);
    await submit(afterClosure);
    assert.deepEqual(sent.map(([, body, revision])=>[body.content_base64,body.safe_photo_declared,revision]),
      [['AAAA',true,1],['AAAA',true,2]]);
  } finally {
    globalThis.FileReader = originalReader;
  }
});

for (const recordId of [undefined, 'record']) {
  test(`closing an unconfirmed save preserves the current editor for ${recordId ?? 'new intake'}`, () => {
    const owner = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'Intake');
    const props = {scope:'account', organizations:['business']};
    const find = name => nodes(owner.render(props), node => node.type?.name === name)[0];
    nodes(owner.render(props), node => node.type === 'Select')[0].props.onValueChange('business');
    const original = find('Records');
    original.props.lock('save', true, 'test-close-save', recordId, true, recordId ? 2 : 1,body.watch_id);
    find('IntakeReceiptRecovery').props.onClosed();
    const current = find('Records');
    assert.equal(current.key, original.key);
    assert.equal(current.props.navigationLocked, false);
    assert.equal(current.props.closedSave, 'test-close-save');
    assert.equal(find('IntakeReceiptRecovery'), undefined);
  });
}

test('a closed save gets a fresh key and direct acknowledgements must match the operation', async () => {
  const slots = [];
  let cursor = 0;
  const hooks = {
    useState(initial) {
      const index = cursor++;
      slots[index] ??= initial;
      return [slots[index], value => { slots[index] = value; }];
    },
    useRef(initial) {
      const index = cursor++;
      return slots[index] ??= {current: initial};
    },
    useEffect(effect, dependencies) {
      const index = cursor++;
      if (!slots[index] || dependencies.some((value, i) => value !== slots[index][i])) {
        slots[index] = dependencies;
        effect();
      }
    },
  };
  const sent = [];
  let patchReply = {};
  const {useWrite: writeHook} = compile(new URL('../../../../web/features/maintenance/common.tsx',import.meta.url), name => {
    if (name === 'react') return hooks;
    if (name === './submission') return submissionModule.exports;
    if (name === '@/lib/api/client') return {ApiError: class extends Error {}};
    if (name === '@/features/identity/session') return {authenticatedRequest: async (_path, options) => {
      sent.push([options.headers['Idempotency-Key'], JSON.parse(options.body)]);
      if (sent.length === 1) throw new Error('lost_response');
      return {revision:1, id:'00000000-0000-0000-0000-000000000001',
        operation_id:options.headers['Idempotency-Key'], organization_id:'business', order_id:'order',
        state:'awaiting_intake', ...patchReply};
    }};
    return {};
  });
  const locks = [];
  const render = closed => { cursor = 0; return writeHook('account', undefined, (...binding) => locks.push(binding), closed); };
  await render().save('intake/records?organization_id=business', {order_id:'order', reported_issue:'Draft observation'});
  assert.equal(render().locked, true);
  const closed = sent[0][0];
  assert.deepEqual(locks.at(-1), [true, closed, true, 1, 'order']);
  render(closed);
  assert.equal(render(closed).locked, false);
  await render(closed).save('intake/records?organization_id=business', {order_id:'order', reported_issue:'Corrected draft observation'});
  assert.equal(sent.length, 2);
  assert.notEqual(sent[1][0], closed);
  assert.equal(sent[1][1].reported_issue, 'Corrected draft observation');
  const target = '00000000-0000-0000-0000-000000000002';
  const attachment = '00000000-0000-0000-0000-000000000003';
  const path = `intake/records/${target}/evidence?organization_id=business`;
  const file = {kind:'condition_photo'};
  const valid = {record_id:target, id:attachment, revision:4};
  for (const invalid of [{record_id:attachment}, {revision:5}, {id:null},
    {operation_id:'test-wrong-operation'}, {organization_id:'other'}]) {
    patchReply = {...valid, ...invalid};
    assert.equal(await render(closed).save(path, file, 3, 'POST'), undefined);
    assert.equal(render(closed).locked, true);
    assert.equal(render(closed).reference, sent[2][0]);
    assert.deepEqual(locks.at(-1), [true, sent[2][0], true, 4, undefined]);
  }
  patchReply = valid;
  assert.equal((await render(closed).save(path, file, 3, 'POST')).id, attachment);
  assert.equal(render(closed).locked, false);

});


test('custody invalidation at the same revision hides assessed findings and retains reported notes', () => {
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'IntakeForm');
  const data = {id:'record', revision:1, custody_receipt_id:'receipt', custody_verification:'current',
    assessment_allowed:true, private_record:{currency:'USD', assessed_issue:'Bench finding', reported_issue:'Customer report'}};
  const props = {scope:'account', organization:'business', data};
  const field = (tree, name) => nodes(tree, node => node.props?.label === name)[0];
  const first = view.render(props);
  assert.equal(field(first, 'assessed_issue').props.value, 'Bench finding');
  field(first, 'reported_issue').props.onValueChange('Unsent observation');

  for (const custody_verification of ['unconfirmed', 'unavailable']) {
    const refreshed = view.render({...props, data:{...data, custody_verification,
      assessment_allowed:false, private_record:{...data.private_record, assessed_issue:''}}});
    assert.equal(field(refreshed, 'assessed_issue').props.value, '');
    assert.equal(field(refreshed, 'assessed_issue').props.readOnly, true);
    assert.equal(field(refreshed, 'reported_issue').props.value, 'Unsent observation');
  }
});

test('custody refresh withholds opening until the current answer returns', () => {
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'Editor');
  const props = {scope:'account', organization:'business', id:'record', saved(){}, lock(){}};
  const data = {id:'record', revision:2, custody_receipt_id:'receipt', custody_verification:'current',
    diagnosis_allowed:true, assessment_allowed:true, current_opening_fee_minor:5000,
    private_record:{reported_issue:'Private notes', assessed_issue:'Bench finding'}};
  const editor = read => nodes(view.render(props, read), node => node.type?.name === 'IntakeForm')[0];
  const initial = editor({data});
  for (const status of [{isFetching:true}, {isPaused:true}]) {
    const pending = editor({data, ...status});
    assert.equal(pending.key, initial.key);
    assert.equal(pending.props.data.custody_verification, 'checking');
    assert.equal(pending.props.data.diagnosis_allowed, false);
    assert.equal(pending.props.data.assessment_allowed, false);
    assert.equal(pending.props.data.current_opening_fee_minor, undefined);
    assert.equal(pending.props.data.private_record.reported_issue, 'Private notes');
  }
  assert.equal(editor({data, isFetching:false}).props.data.diagnosis_allowed, true);
});

test('same-revision custody recovery restores the finding and allows the assessor to save edits', () => {
  const writes = [];
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'IntakeForm', {
    '../common': {useCopy:()=>({t:key=>key}), useWrite:()=>({save:async (...args)=>{writes.push(args);}})},
  });
  const props = {scope:'account', organization:'business', data:{
    id:'record', revision:3, custody_receipt_id:'receipt', custody_verification:'unavailable',
    private_record:{currency:'USD', reported_issue:'Customer report', assessed_issue:''},
  }};
  const field = (tree, name) => nodes(tree, node => node.props?.label === name)[0];
  field(view.render(props), 'reported_issue').props.onValueChange('Unsent observation');
  const recovered = {...props, data:{...props.data, custody_verification:'current', assessment_allowed:true,
    current_assessment_custody:{watch_id:'watch',watch_revision:1,receipt_id:'receipt',
      receipt_revision:1,incident_revision:0},
    private_record:{...props.data.private_record, assessed_issue:'Restored bench finding'}}};
  const submit = tree => nodes(tree, node => node.type === 'form')[0].props.onSubmit({preventDefault(){}});
  submit(view.render(props));
  assert.equal(writes.length, 0);
  const restored = view.render(recovered);
  assert.equal(field(restored, 'assessed_issue').props.value, 'Restored bench finding');
  assert.equal(field(restored, 'assessed_issue').props.readOnly, false);
  submit(restored);
  assert.equal(writes[0][1].assessed_issue, 'Restored bench finding');
  field(restored, 'assessed_issue').props.onValueChange('Updated bench finding');
  const edited = view.render(recovered);
  assert.equal(field(edited, 'reported_issue').props.value, 'Unsent observation');
  assert.equal(field(edited, 'assessed_issue').props.value, 'Updated bench finding');
  submit(edited);
  assert.equal(writes[1][1].assessed_issue, 'Updated bench finding');
  assert.equal(writes[1][1].reported_issue, 'Unsent observation');
  assert.equal(writes[1][2], 3);
  assert.deepEqual(writes[1][1].reviewed_assessment_custody,recovered.data.current_assessment_custody);
  const newer = {...recovered, data:{...recovered.data,
    current_assessment_custody:{...recovered.data.current_assessment_custody,receipt_revision:2},
    private_record:{...recovered.data.private_record,assessed_issue:''},
  }};
  const stale = view.render(newer);
  assert.equal(field(stale,'assessed_issue').props.value,'');
  assert.equal(field(stale,'reported_issue').props.value,'Unsent observation');
  assert.ok(nodes(stale,node=>node.props?.children==='assessmentCustodyChanged').length);
  submit(stale);
  assert.equal(writes.length,2);
  field(stale,'assessed_issue').props.onValueChange('New bench finding');
  submit(view.render(newer));
  assert.equal(writes[2][1].reviewed_assessment_custody.receipt_revision,2);
  assert.equal(writes[2][1].assessed_issue,'New bench finding');
});

test('destination withdrawal during photo preparation keeps the draft for another business', async () => {
  class ApiError extends Error {
    status = 409;
    code = 'destination_ineligible';
  }
  const previousReader = globalThis.FileReader;
  globalThis.FileReader = class {
    readAsDataURL() {
      this.result = 'data:image/png;base64,AAAA';
      this.onload();
    }
  };
  try {
    const original = {organization_id:'business', interventions:['limited_maintenance']};
    const replacement = {...original, organization_id:'replacement'};
    const context = {actor_id:'buyer', subject_id:'buyer', watch_id:'watch', watch_revision:1,
      destinations:[original]};
    const sent = [];
    const view = viewHarness('../../../../web/features/maintenance/request.tsx','RequestForm',{
      '@/lib/api/client': {ApiError},
      './common': {useCopy:()=>({t:key=>key,locale:'en'}), Recovery:'Recovery',
        call:async(_scope,path)=>{sent.push(path);throw new ApiError();}},
    });
    const props = {scope:'account', context, onDenied:()=>assert.fail('Buyer access remains current'),
      reviewContext:async()=>({...context,destinations:[replacement]})};
    const find = predicate => nodes(view.render(props), predicate);
    find(node=>node.type==='Select')[0].props.onValueChange('business');
    find(node=>node.type==='Textarea')[0].props.onValueChange('Private symptoms');
    find(node=>node.type==='Textarea')[1].props.onValueChange('Private modifications');
    const file = {type:'image/png',size:12};
    find(node=>node.type==='input')[0].props.onChange({target:{files:[file]}});
    for(const checkbox of find(node=>node.type==='Checkbox'))checkbox.props.onCheckedChange(true);
    find(node=>node.type==='form')[0].props.onSubmit({preventDefault(){}});
    for(let tick=0;tick<12;tick++)await Promise.resolve();
    assert.deepEqual(sent,['maintenance/photos']);
    assert.equal(find(node=>node.props?.children==='checkRequestReceipt').length,0);
    find(node=>node.props?.children==='reviewContext')[0].props.onClick();
    await Promise.resolve();
    find(node=>node.props?.children==='adoptContext')[0].props.onClick();
    const [selector]=find(node=>node.type==='Select');
    assert.deepEqual(selector.props.options.map(option=>option.value),['replacement']);
    assert.deepEqual(find(node=>node.type==='Textarea').map(node=>node.props.value),
      ['Private symptoms','Private modifications']);
    assert.ok(find(node=>Array.isArray(node.props?.children)&&node.props.children[0]==='selectedFiles'&&
      node.props.children.at(-1)==='1').length);
    assert.equal(find(node=>node.type==='Checkbox')[0].props.checked,false);
  } finally {
    globalThis.FileReader = previousReader;
  }
});

for (const action of ['lookup', 'close']) {
  test(`new intake ${action} retains the operation until a valid record is confirmed`, async () => {
    class ApiError extends Error {
      status = 404;
      code = 'operation_missing';
    }

    const binding = {reference: 'test-create-intake', orderId: body.watch_id, expectedRevision: 1};
    const receipt = {operation_id: binding.reference, organization_id: 'business', kind: 'save', revision: 1};
    const recovered = [];
    const calls = [];
    const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'IntakeReceiptRecovery', {
      '@/lib/api/client': {ApiError},
      '../common': {
        useCopy: () => ({t: key => key}), Recovery: 'Recovery',
        call: async (_scope, _path, options) => {
          const command = JSON.parse(options.body);
          assert.equal(command.operation_id, binding.reference);
          calls.push(command.action);
          if (command.action !== action) throw new ApiError();
          return {...receipt, record_id: recordId, order_id: orderId};
        },
      },
    });
    const props = {scope: 'account', organization: 'business', kind: 'save', binding,
      onRecovered: result => recovered.push(result), onClosed: () => assert.fail('Expected a receipt')};
    const find = predicate => nodes(view.render(props), predicate);
    const press = async label => {
      const button = find(node => node.props?.children === label)[0];
      (button?.props.onClick ?? find(node => node.type === 'Recovery')[0].props.retry)();
      for (let tick = 0; tick < 6; tick++) await Promise.resolve();
    };
    let recordId, orderId;
    for ([recordId, orderId] of [
      ...[undefined, null, 7, '', 'invalid', requestId + '\n'].map(id => [id, body.watch_id]),
      [requestId, undefined], [requestId, requestId], [requestId, body.watch_id],
    ]) {
      if (action === 'close') await press('checkIntakeReceipt');
      await press(action === 'close' ? 'closeUnconfirmed' : 'checkIntakeReceipt');
      if (recordId === requestId && orderId === body.watch_id) break;
      assert.deepEqual(recovered, []);
      assert.equal(find(node => node.type === 'bdi')[0].props.children, binding.reference);
      assert.equal(find(node => node.type === 'Recovery').length, 1);
    }
    assert.deepEqual(recovered, [{...receipt, record_id: requestId, order_id: body.watch_id}]);
    assert.equal(calls.filter(value => value === action).length, 9);
  });
}

test('staff can explicitly review and save a newer revision of the same custody receipt', async () => {
  const writes = [];
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'IntakeForm', {
    '../common': {useCopy: () => ({t: key => key, locale:'en'}),
      useWrite: () => ({save: async (...args) => {writes.push(args);}})},
  });
  const binding = {watch_id:'watch', watch_revision:2, receipt_id:'receipt',
    receipt_revision:3, incident_revision:1};
  const props = {scope:'account', organization:'business', data:{
    id:'record', order_id:'order', revision:4, custody_receipt_id:'receipt',
    custody_verification:'unconfirmed', receipt_revision_for_review:binding,
    private_record:{currency:'USD', reported_issue:'Saved report', assessed_issue:''},
  }};
  const find = (predicate, current=props) => nodes(view.render(current), predicate)[0];
  const submit = current => find(node => node.type === 'form', current).props.onSubmit({preventDefault() {}});
  find(node => node.props?.label === 'reported_issue').props.onValueChange('Unsent details');
  submit();
  assert.equal(writes.length, 0);
  find(node => node.props?.children === 'reviewReceiptRevision').props.onClick();
  const changed = {...props, data:{...props.data, receipt_revision_for_review:{...binding, incident_revision:2}}};
  submit(changed);
  assert.equal(writes.length, 0);
  find(node => node.props?.children === 'reviewReceiptRevision', changed).props.onClick();
  submit(changed);
  assert.equal(writes[0][1].custody_receipt_id, 'receipt');
  assert.equal(writes[0][1].reported_issue, 'Unsent details');
  assert.equal(writes[0][1].reviewed_receipt_revision.incident_revision, 2);
  assert.equal(writes[0][2], 4);
});

test('a replacement custody receipt needs review before the intake can be saved', async () => {
  const writes = [];
  const replacements = [photoReference(1), requestId];
  const watchId = photoReference(2);
  let checkedId;
  const view = viewHarness('../../../../web/features/maintenance/intake/index.tsx', 'IntakeForm', {
    '../common': {
      useCopy: () => ({t: key => key, locale:'ar'}),
      useWrite: () => ({save: async (...args) => {writes.push(args);}}),
      call: async (_scope, path) => {
        checkedId = new URLSearchParams(path.split('?')[1]).get('review_receipt_id');
        return {revision:4, receipt_revision_for_review:{receipt_id:checkedId, receipt_revision:3,
          watch_id:watchId, watch_revision:2, incident_revision:1}};
      },
    },
  });
  const props = {scope:'account', organization:'business', data:{
    id:'record', order_id:'order', revision:4, custody_receipt_id:'original',
    custody_verification:'unconfirmed',
    private_record:{currency:'USD', reported_issue:'Saved report', assessed_issue:''},
  }};
  const find = predicate => nodes(view.render(props), predicate)[0];
  const submit = () => find(node => node.type === 'form').props.onSubmit({preventDefault() {}});
  const select = value => find(node => node.props?.label === 'custody_receipt_id').props.onValueChange(value);
  const check = async () => {
    find(node => node.props?.children === 'checkReplacementReceipt').props.onClick();
    await Promise.resolve();
  };
  const approve = () => find(node => node.props?.children === 'reviewReceiptRevision').props.onClick();
  select(replacements[0]);
  submit();
  await check();
  submit();
  assert.equal(writes.length, 0);
  approve();
  select(replacements[1]);
  submit();
  assert.equal(writes.length, 0);
  await check();
  approve();
  submit();
  assert.equal(checkedId, replacements[1]);
  assert.deepEqual(writes[0][1].reviewed_receipt_revision, {
    receipt_id:replacements[1], receipt_revision:3,
    watch_id:watchId, watch_revision:2, incident_revision:1,
  });
  assert.equal(writes[0][2], 4);
});

test('replacing a photo during preparation requires a new declaration and uploads only the replacement', async () => {
  const previousReader = globalThis.FileReader;
  const reads = [];
  globalThis.FileReader = class {
    readAsDataURL(file) {
      reads.push(() => {
        this.result = 'data:image/png;base64,' + file.bytes;
        this.onload();
      });
    }
  };
  try {
    const uploads = [];
    const view = viewHarness('../../../../web/features/maintenance/intake/evidence.tsx', 'default', {
      '../common': {
        useCopy: () => ({t: key => key, locale: 'en'}),
        useWrite: () => ({save: async (_path, body) => { uploads.push(body); return {revision: 2}; }}),
      },
    });
    const props = {scope: 'account', organization: 'business', id: 'record', revision: 1, changed() {}};
    const read = {data: {items: []}, refetch() {}};
    const control = type => nodes(view.render(props, read), node => node.type === type)[0];
    const select = bytes => control('input').props.onChange({
      target: {files: [{type: 'image/png', size: 10, bytes}]},
    });
    const submit = () => control('form').props.onSubmit({preventDefault() {}});
    const settle = async () => { for (let tick = 0; tick < 6; tick++) await Promise.resolve(); };

    select('AAAA');
    control('Checkbox').props.onCheckedChange(true);
    submit();
    assert.equal(reads.length, 1);
    select('BBBB');
    assert.equal(control('Checkbox').props.checked, false);
    reads.shift()();
    await settle();
    assert.deepEqual(uploads, []);

    submit();
    assert.equal(reads.length, 0);
    control('Checkbox').props.onCheckedChange(true);
    submit();
    reads.shift()();
    await settle();
    assert.deepEqual(uploads.map(({content_base64, safe_photo_declared}) =>
      [content_base64, safe_photo_declared]), [['BBBB', true]]);
  } finally {
    globalThis.FileReader = previousReader;
  }
});

test('business intake requires the assigned queue response before using it', async () => {
  const file = new URL('../../../../web/features/maintenance/intake/reads.ts',import.meta.url);
  const legacyQueue = {items:[],next_offset:null};
  const currentQueue = {...legacyQueue,intake_contract:'current',total:0};
  const unavailable = new Error('assignment unavailable');
  const signal = new AbortController().signal;
  for (const answer of [legacyQueue, unavailable, currentQueue]) {
    const {intakeRead} = compile(file, name => ({
      '@/lib/page-speed/definition': {definePageRead: definition => definition},
      '../common': {async call(scope,path,options) {
        assert.equal(scope,'test-staff-scope');
        assert.equal(path,'intake/records?organization_id=business&offset=0');
        assert.equal(options.signal,signal);
        if (answer instanceof Error) throw answer;
        return answer;
      }},
    })[name]);
    const read = intakeRead.ask(signal,'test-staff-scope','business',0);
    if (answer === currentQueue) assert.deepEqual(await read,currentQueue);
    else if (answer === unavailable) await assert.rejects(read,error=>error===unavailable);
    else await assert.rejects(read,/intake_contract_unavailable/);
  }
});

test('mounted intake reads retain drafts through refresh and fence old private answers', async () => {
  const effects = [];
  let effectIndex = 0;
  const view = viewHarness('../../../../web/features/maintenance/intake/mounted-read.ts', 'useMountedIntakeRead', hooks => ({
    react: {...hooks, useEffect(effect, deps) {
      const index = effectIndex++;
      const prior = effects[index];
      if (prior && deps.every((value, position) => Object.is(value, prior.deps[position]))) return;
      prior?.cleanup?.();
      effects[index] = {deps, cleanup: effect()};
    }},
  }));
  const calls = [];
  const question = scope => ({key: ['intake', scope], ask: signal => new Promise((resolve, reject) => {
    calls.push({signal, resolve, reject});
  })});
  const first = question('first'), second = question('second');
  const render = read => {
    effectIndex = 0;
    return view.render(read);
  };

  assert.equal(render(first).isPending, true);
  calls[0].resolve({revision: 1});
  await Promise.resolve();
  const initial = render(first);
  assert.deepEqual(initial.data, {revision: 1});
  initial.refetch();
  const refreshing = render(first);
  assert.equal(refreshing.isFetching, true);
  assert.deepEqual(refreshing.data, {revision: 1});
  calls[1].reject({status: 503});
  await Promise.resolve();
  assert.deepEqual(render(first).data, {revision: 1});

  render(first).refetch();
  render(first);
  assert.equal(render(second).data, undefined);
  assert.equal(calls[2].signal.aborted, true);
  calls[2].resolve({revision: 2});
  calls[3].resolve({revision: 3});
  await Promise.resolve();
  assert.deepEqual(render(second).data, {revision: 3});

  render(second).refetch();
  render(second);
  calls[4].reject({status: 403});
  await Promise.resolve();
  assert.equal(render(second).data, undefined);
  assert.equal(render(second).error.status, 403);
});

test('unavailable photos reprepare only after scoped lookup and preserve the original request', async () => {
  const photo = {operation_id:'photo-1',media_type:'image/png',content_base64:'AAAA'};
  const submission = new Submission(body,[photo]);
  const signal = new AbortController().signal;
  const uploads = [];
  const sent = [];
  let lookup = 'missing';
  const unavailable = {status:409,code:'photo_unavailable'};
  const transport = {
    upload: async (prepared, command) => {
      uploads.push(prepared.operation_id);
      assert.equal(command.operation_id, body.operation_id);
      assert.equal(prepared.content_base64, photo.content_base64);
      if (uploads.length === 2) throw new Error('lost_upload_response');
      return uploadReceipt(prepared, command, uploads.length === 1 ? 1 : 2);
    },
    lookup: async command => {
      assert.equal(command.operation_id, body.operation_id);
      if (lookup === 'committed') return reply;
      if (lookup === 'unavailable') throw new Error('unavailable');
      throw {status:404,code:'operation_missing'};
    },
    submit: async command => {
      sent.push(command);
      if (sent.length === 1) throw unavailable;
      return reply;
    },
  };
  await assert.rejects(submission.run(transport, signal), error => error === unavailable);
  lookup = 'unavailable';
  await assert.rejects(submission.run(transport, signal), /unavailable/);
  assert.deepEqual(uploads, [photo.operation_id]);
  lookup = 'committed';
  assert.equal(await submission.run(transport, signal), reply);
  assert.deepEqual(uploads, [photo.operation_id]);
  lookup = 'missing';
  await assert.rejects(submission.run(transport, signal), /lost_upload_response/);
  assert.equal(await submission.run(transport, signal), reply);
  assert.notEqual(uploads[1], uploads[0]);
  assert.equal(uploads[2], uploads[1]);
  assert.deepEqual(sent, [1, 2].map(index => ({...body, photo_refs:[photoReference(index)]})));
});

test('a watch commitment conflict preserves the private draft and retries the original admission', async () => {
  class ApiError extends Error {
    constructor(status, code) { super(code); this.status = status; this.code = code; }
  }
  const sent = [];
  let denied = false;
  const view = viewHarness('../../../../web/features/maintenance/request.tsx', 'RequestForm', {
    '@/lib/api/client': {ApiError},
    './common': {useCopy: () => ({t: key => key, locale: 'en'}), call: async (_scope, path, options) => {
      if (options.method === 'GET') throw new ApiError(404, 'operation_missing');
      const command = JSON.parse(options.body);
      sent.push(command);
      if (sent.length === 1) throw new ApiError(409, 'watch_committed');
      return {...command, request_id: requestId, revision: 1, state: 'submitted'};
    }},
  });
  const props = {scope: 'account', onDenied: () => { denied = true; }, context: {
    actor_id: 'customer', subject_id: 'customer', watch_id: 'watch', watch_revision: 1,
    destinations: [{organization_id: 'business', brand_id: 'brand', capability_revision: 1,
      policy_revision: 1, interventions: ['limited_maintenance']}],
  }};
  const find = predicate => nodes(view.render(props), predicate);
  const settle = async () => { for (let tick = 0; tick < 14; tick++) await Promise.resolve(); };
  find(node => node.type === 'Select')[0].props.onValueChange('business');
  find(node => node.type === 'Textarea')[0].props.onValueChange('Private symptoms');
  find(node => node.type === 'Checkbox')[0].props.onCheckedChange(true);
  find(node => node.type === 'form')[0].props.onSubmit({preventDefault() {}});
  await settle();
  assert.equal(denied, false);
  assert.equal(find(node => node.props?.label === 'symptoms')[0].props.value, 'Private symptoms');
  assert.equal(find(node => node.props?.title === 'watchCommitted').length, 1);
  assert.equal(find(node => node.props?.children === 'checkRequestReceipt').length, 1);
  assert.equal(find(node => node.type === 'bdi')[0].props.children, sent[0].operation_id);
  find(node => node.props?.children === 'retry')[0].props.onClick();
  await settle();
  assert.deepEqual(sent, [sent[0], sent[0]]);
  assert.equal(find(node => node.props?.children === 'requestSubmitted').length, 1);
});
