import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../../../../web/public/push-events.js',import.meta.url),'utf8');
function worker() {
  const handlers={},shown=[],opened=[];
  const self={addEventListener:(name,fn)=>{handlers[name]=fn;},registration:{showNotification:async(...args)=>{shown.push(args);}},clients:{openWindow:async url=>{opened.push(url);}},location:{origin:'https://beirut-time.invalid'}};
  vm.runInNewContext(source,{self,URL});
  return {handlers,shown,opened};
}
test('generic bilingual notice ignores all private source fields',async()=>{
  const {handlers,shown}=worker();let promise;
  handlers.push({data:{json:()=>({schema_version:'browser-push.v1',kind:'notice',body:'private contact',url:'https://untrusted.invalid'})},waitUntil:value=>{promise=value;}});
  await promise;
  assert.equal(shown.length,1);
  assert.match(shown[0][1].body,/inbox/);
  assert.match(shown[0][1].body,/صندوق/);
  assert.doesNotMatch(JSON.stringify(shown),/private contact|untrusted/);
});
test('invalid payload is ignored',()=>{
  const {handlers,shown}=worker();
  for(const data of [null,{json:()=>{throw Error();}},{json:()=>({schema_version:'unknown',kind:'notice'})}]) handlers.push({data,waitUntil:()=>{throw Error();}});
  assert.equal(shown.length,0);
});
test('click opens only the same-origin authenticated inbox',async()=>{
  const {handlers,opened}=worker();let promise,closed=false;
  handlers.notificationclick({notification:{tag:'bt-inbox',data:{destination:'https://untrusted.invalid'},close:()=>{closed=true;}},waitUntil:value=>{promise=value;}});
  await promise;
  assert.equal(closed,true);
  assert.deepEqual(opened,['https://beirut-time.invalid/inbox']);
});
