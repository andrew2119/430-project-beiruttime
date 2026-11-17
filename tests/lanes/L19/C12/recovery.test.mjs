import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from '../../../../web/node_modules/typescript/lib/typescript.js';
const source=path=>readFileSync(new URL(`../../../../web/features/${path}`,import.meta.url),'utf8');
class ApiError extends Error { constructor(status){super();this.status=status;} }
const compile=text=>ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;

test('private read clears denied records and preserves availability recovery',async()=>{
  for(const status of [401,403,408,429,503]){
    const values=[];let index=0,effect,fail=false;
    const answer={page:0,total:1,consents:[{id:'private-record'}]};
    const read={ask:async()=>{if(fail)throw new ApiError(status);return answer;}};
    const react={useMemo:()=>read,useState:initial=>{
      const slot=index++;if(!(slot in values))values[slot]=initial;
      return [values[slot],value=>{values[slot]=typeof value==='function'?value(values[slot]):value;}];
    },useEffect:callback=>{effect=callback;},useCallback:callback=>callback};
    const exports={};
    new Function('require','exports',compile(source('consent/use-consent-read.ts')))(name=>{
      if(name==='react')return react;
      if(name==='./reads')return {consentRead:()=>read};
      if(name==='@/lib/api/client')return {ApiError};
      throw new Error(name);
    },exports);
    const render=()=>{index=0;return exports.useConsentRead('current-access',0);};
    render();effect();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(render().data,answer);
    fail=true;effect();await new Promise(resolve=>setImmediate(resolve));
    const result=render();
    assert.equal(result.denied,status===401||status===403);
    assert.equal(result.data,status===401||status===403?undefined:answer);
    assert.equal(result.error.status,status);
    fail=false;effect();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(render().data,answer);assert.equal(render().error,null);
  }
});

for(const feature of ['consent/consent-view.tsx','eligibility/decision-view.tsx']){
  test(`${feature}: lost response and retry rejection keep exact command`,async()=>{
    const tree=ts.createSourceFile(feature,source(feature),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
    let submit;
    function visit(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='submit')submit=node;ts.forEachChild(node,visit);}
    visit(tree);assert.ok(submit);
    const calls=[],operation={current:null},references=[];
    const form={reset(){}};
    const data={get:key=>({request_id:'request',brand_id:'brand',request_revision:'1',consent:'consent',revision:'0',reason:'Policy checked.'})[key]};
    let status=503;
    const dependencies={pending:false,decision:'refuse',verdict:'correction',operation,fingerprint:'current-access',path:'/private',
      ApiError,FormData:class {constructor(){return data;}},normalizeDigits:value=>value,
      crypto:{randomUUID:()=>`operation-${calls.length}`},
      authenticatedRequest:async(_path,options)=>{calls.push(options);if(status)throw new ApiError(status);return {state:'eligible',consent:{id:'consent'}};},
      setPending(){},setError(){},setResult(){},setLocked(){},setUncertain(){},setDecision(){},setAcknowledged(){},
      setReference:value=>references.push(value),query:{refetch:async()=>{}}};
    const run=new Function(...Object.keys(dependencies),`${compile(submit.getText(tree))};return submit;`)(...Object.values(dependencies));
    for(status of [503,408,429,401,403,0])await run({preventDefault(){},currentTarget:form});
    assert.equal(calls.length,6);
    assert.ok(calls.every(call=>call.body===calls[0].body));
    assert.ok(references.filter(Boolean).every(value=>value==='operation-0'));
    if(feature.startsWith('consent/'))assert.ok(calls.every(call=>call.headers['Idempotency-Key']==='operation-0'));
    assert.equal(operation.current,null);
  });
}
