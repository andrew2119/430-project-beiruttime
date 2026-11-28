import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
const root=new URL('../../../../',import.meta.url);
const requireWeb=createRequire(realpathSync(new URL('web/node_modules/eslint/package.json',root)));
const Validator=requireWeb('ajv');
for(const folder of ['packages/contracts-service/directory/','packages/contracts-catalog/options/movement/']) {
  test(`${folder} operation examples validate and preserve uncertain references`,()=>{
    const schema=JSON.parse(readFileSync(new URL(`${folder}operation.schema.v1.json`,root),'utf8'));
    // The operation envelope uses only the common object/type/enum vocabulary.
    delete schema.$schema;
    const validate=new Validator({allErrors:true}).compile(schema);
    const examples=JSON.parse(readFileSync(new URL(`${folder}fixtures/operations.v1.json`,root),'utf8'));
    for(const example of Object.values(examples))assert.ok(validate(example),JSON.stringify(validate.errors));
    assert.equal(examples.success.operation_id,examples.lost_response.operation_id);
    assert.equal(examples.lost_response.state,'pending');
    assert.equal(validate({...examples.success,revision:1.5}),false);
    assert.equal(validate({...examples.success,private_evidence:'excluded'}),false);
  });
}

test('services declares its feature-owned page and shared read composition',()=>{
  const declaration=JSON.parse(readFileSync(new URL('web/features/service-directory/delivery-contract.json',root),'utf8'));
  assert.deepEqual(Object.keys(declaration).sort(),['route','file','view','kind','reason','content','read','proof'].sort());
  assert.equal(declaration.route,'/services');
  assert.equal(declaration.file,'web/app/(service-directory)/services/page.tsx');
  assert.equal(declaration.view,'web/features/service-directory/view.tsx');
  assert.equal(declaration.kind,'reads');
  assert.equal(declaration.read,'usePageRead');
  assert.equal(declaration.proof,'owed');
  const view=readFileSync(new URL(declaration.view,root),'utf8');
  assert.ok(view.includes('<PageFrame>')&&view.includes('<PageHeader ')&&view.includes('usePageRead('));
});
