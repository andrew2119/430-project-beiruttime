import { readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import assert from 'node:assert/strict';
const require = createRequire(realpathSync(new URL('../../../../web/node_modules/eslint/package.json',import.meta.url)));
const Validator = require('ajv');
const folder = new URL('../../../../packages/contracts-identity/data-requests/',import.meta.url);
const json = path=>JSON.parse(readFileSync(new URL(path,folder),'utf8'));
const validator = new Validator({allErrors:true});
test('positive and lost-response fixtures conform to the versioned schema',()=>{
  const validate=validator.compile(json('operation.v1.schema.json'));
  for (const name of ['success','lost-response']) assert.equal(validate(json(`fixtures/${name}.v1.json`)),true,JSON.stringify(validate.errors));
  assert.equal(validate({...json('fixtures/success.v1.json'),private_file:'excluded'}),false);
});
test('command schema rejects cross-account fields and changed revision',()=>{
  const validate=validator.compile(json('command.v1.schema.json'));
  const command={schema_version:'data-requests.v1',operation_id:'request-1',kind:'delete',expected_revision:0};
  assert.equal(validate(command),true);
  assert.equal(validate({...command,subject_id:'person-2'}),false);
  assert.equal(validate({...command,expected_revision:1}),false);
});
