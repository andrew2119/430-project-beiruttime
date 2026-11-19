import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pageContractIssues } from '../../../../web/scripts/check-page-contract.mjs';

const page = {route:'/care/reduction',file:'web/app/(reduction)/care/reduction/page.tsx',view:'web/features/reduction/view.tsx',kind:'reads',reason:'Scoped care read.',content:'[data-page-answer]',read:'reduction',proof:'owed'};
function fixture(run) {
  const root = mkdtempSync(join(tmpdir(),'page-contract-test-'));
  const put = (file,value)=>{mkdirSync(join(root,file,'..'),{recursive:true});writeFileSync(join(root,file),typeof value === 'string' ? value : JSON.stringify(value));};
  put('web/lib/page-speed/pages.json',[{route:'/internal/components',file:'web/app/internal/components/page.tsx',kind:'static',reason:'Component board.',content:'[data-page-answer]',read:'none',proof:'owed'}]);
  put('web/app/internal/components/page.tsx','export default function Page(){return null;}');
  put('web/tests/page-migration.json',{reason:'No frozen pages.',pages:[],shell:{}});
  put(page.file,"import { View } from '@/features/reduction/view'; export default function Page(){return <View/>;}");
  put(page.view,"import { PageFrame, PageHeader } from '@/shell/foundation/page'; import { usePageRead } from '@/lib/page-speed/read'; export function View(){const answer = usePageRead(null); return <PageFrame><PageHeader title='Care'/></PageFrame>;}");
  try {run(root,put);} finally {rmSync(root,{recursive:true,force:true});}
}
test('feature declarations accept object and array forms with shared reads',()=>fixture((root,put)=>{
  for (const declared of [page,[page]]) {put('web/features/reduction/delivery-contract.json',declared);assert.deepEqual(pageContractIssues(root),[]);}
}));
test('unregistered product pages still fail',()=>fixture(root=>assert.ok(pageContractIssues(root).some(error=>error.includes('no delivery contract')))));
for (const [name,change] of Object.entries({route:{route:'/wrong'},view:{view:'web/features/other/view.tsx'},proof:{proof:'passed'},read:{read:'none'},reserved:{route:'/internal/care',file:'web/app/internal/care/page.tsx'}})) {
  test(`rejects invalid feature ${name}`,()=>fixture((root,put)=>{put('web/features/reduction/delivery-contract.json',{...page,...change});assert.ok(pageContractIssues(root).length);}));
}
test('duplicates across feature declarations and page tables fail',()=>fixture((root,put)=>{
  put('web/features/reduction/delivery-contract.json',page);
  put('web/features/other/delivery-contract.json',{...page,view:'web/features/other/view.tsx'});
  assert.ok(pageContractIssues(root).some(error=>error.includes('Duplicate page')));
  put('web/features/other/delivery-contract.json',[]);
  put('web/lib/page-speed/pages.json',[{...page,file:'web/app/internal/page.tsx',route:'/internal/page',view:'web/internal/page/view.tsx',read:'page-demo'}]);
  put('web/features/reduction/delivery-contract.json',{...page,route:'/internal/page'});
  assert.ok(pageContractIssues(root).some(error=>error.includes('Duplicate page')));
}));
test('declared views must compose the shared frame and use shared reads',()=>fixture((root,put)=>{
  put('web/features/reduction/delivery-contract.json',page);
  put(page.view,'export function View(){return <div/>;}');
  const errors=pageContractIssues(root);
  assert.ok(errors.some(error=>error.includes('shared page composition')));
  assert.ok(errors.some(error=>error.includes('mounted reads')));
}));
