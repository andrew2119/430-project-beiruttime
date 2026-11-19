import {test} from 'node:test';
import assert from 'node:assert/strict';
import {navigate, navigationMatches} from './ctx.mjs';

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
