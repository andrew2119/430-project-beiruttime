import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from '../../../../web/node_modules/typescript/lib/typescript.js';
const root=new URL('../../../../',import.meta.url);
const source=path=>readFileSync(new URL(path,root),'utf8');
for(const path of ['web/features/consent/consent-view.tsx','web/features/eligibility/decision-view.tsx']){
  const text=source(path), tree=ts.createSourceFile(path,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  test(`${path}: form submission uses an explicit submit control`,()=>{
    let forms=0,submits=0;
    function visit(node){
      if(ts.isJsxOpeningElement(node)&&node.tagName.getText(tree)==='form')forms++;
      if((ts.isJsxOpeningElement(node)||ts.isJsxSelfClosingElement(node))&&node.tagName.getText(tree)==='Button'){
        if(node.attributes.properties.some(attr=>ts.isJsxAttribute(attr)&&attr.name.getText(tree)==='type'&&attr.initializer?.text==='submit'))submits++;
      }
      ts.forEachChild(node,visit);
    }
    visit(tree);assert.ok(forms>0);assert.equal(submits,forms);
  });
  test(`${path}: private command memory is not persisted or keyed by language`,()=>{
    assert.doesNotMatch(text,/localStorage|sessionStorage|document\.cookie|indexedDB/);
    function visit(node){
      if(ts.isJsxAttribute(node)&&node.name.getText(tree)==='key')assert.doesNotMatch(node.getText(tree),/locale|language/);
      ts.forEachChild(node,visit);
    }
    visit(tree);
  });
}
for(const folder of ['consent','eligibility'])test(`${folder}: complete language keys`,()=>{
  const en=JSON.parse(source(`web/features/${folder}/en.json`)),ar=JSON.parse(source(`web/features/${folder}/ar.json`));
  assert.deepEqual(Object.keys(en).sort(),Object.keys(ar).sort());
  for(const copy of [en,ar])for(const value of Object.values(copy))assert.ok(typeof value==='string'&&value.trim());
});
