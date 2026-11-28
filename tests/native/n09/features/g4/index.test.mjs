import assert from 'node:assert/strict';
import test from 'node:test';
import { features } from './index.mjs';

test('exports the sixteen contracted feature entries in order', () => {
  assert.equal(features.length, 16);
  for (const [offset, feature] of features.entries()) {
    const number = 49 + offset;
    assert.equal(feature.feature_id, `F${number}`);
    assert.equal(feature.proof_id, `f${number}-proof`);
    assert.equal(feature.proof_revision, '1');
    assert.deepEqual(Object.keys(feature).sort(), [
      'feature_id', 'journey', 'negative', 'proof_id', 'proof_revision', 'recovery',
    ]);
    for (const scenario of ['journey', 'negative', 'recovery']) {
      assert.equal(typeof feature[scenario], 'function');
    }
  }
});

test('every scenario requires a real signed-in identity and propagates its failure', async () => {
  for (const feature of features) {
    for (const scenario of ['journey', 'negative', 'recovery']) {
      const failure = new Error('test-registration-unavailable');
      let calls = 0;
      const ctx = {
        actor: async role => {
          calls++;
          assert.ok(['buyer','operator','reviewer'].includes(role));
          throw failure;
        },
      };
      await assert.rejects(feature[scenario](ctx), error => error === failure);
      assert.equal(calls,1,`${feature.feature_id} ${scenario} must start with current identity`);
    }
  }
});

 test('an assessment alone cannot pass the work-log prerequisite', async () => {
  const { serviceLifecycle } = await import('./journeys.mjs');
  await assert.rejects(serviceLifecycle({}, {subject:'test-request', operation_id:'test-operation', actor_id:'test-buyer'}), error => {
    assert.equal(error.code, 'service_lifecycle_deferred');
    assert.equal(error.operation_id, 'test-operation');
    assert.equal(error.actor_id, 'test-buyer');
    return true;
  });
});

test('language and mobile refusals retain the invalid page reference in both languages', async () => {
  const { runInNewContext } = await import('node:vm');
  const { words } = await import('./browser.mjs');
  for (const locale of ['en','ar']) {
    for (const number of [62,63]) {
      const translations = Object.fromEntries(await Promise.all(['en','ar'].map(async language =>
        [language,await words({cell:{locale:language}},'discovery')])));
      let address;
      const visited = [];
      const root = {lang:locale,dir:locale === 'ar' ? 'rtl' : 'ltr',dataset:{theme:'dark'}};
      const main = {get innerText() { visited.push(root.lang); return translations[root.lang].rangeError; }};
      const action = {
        get textContent() {return root.lang === 'en' ? 'العربية' : 'English';},
        getClientRects:()=>[{}],getAttribute:()=>null,setAttribute:()=>{},removeAttribute:()=>{},
      };
      const document = {documentElement:root,
        querySelector:selector=>selector === 'main' ? main : action,
        querySelectorAll:()=>[action]};
      const page = {
        goto:async path=>{address=`http://localhost:3000/${locale}${path}`;},
        waitFor:async()=>{},
        evaluate:async(fn,...args)=>runInNewContext(`(${fn.toString()})(...args)`,
          {args,document,window:{fetch:async()=>{}},innerWidth:390,setTimeout}),
        click:async()=>{
          root.lang=root.lang === 'en' ? 'ar' : 'en';
          root.dir=root.lang === 'ar' ? 'rtl' : 'ltr';
          address=address.replace(/^http:\/\/localhost:3000\/(en|ar)\//,`http://localhost:3000/${root.lang}/`);
        },
        exists:async()=>false,url:async()=>address,
      };
      const ctx = {origin:'http://localhost:3000',cell:{locale,theme:'dark',width:390},page,
        actor:async()=>({actor_id:'test-buyer'}),signIn:async()=>{}};
      const value = await features.find(feature=>feature.feature_id === `F${number}`).negative(ctx);
      assert.deepEqual(value,{operation_id:`http://localhost:3000/${locale}/watches?min_price=20&max_price=10`,actor_id:'test-buyer'});
      assert.equal(root.lang,locale);
      assert.deepEqual(visited,number === 62 ? [locale,locale === 'ar' ? 'en' : 'ar',locale] : [locale]);
      page.url=async()=>`http://localhost:3000/${locale}/watches/test-unrelated-record`;
      await assert.rejects(features.find(feature=>feature.feature_id === `F${number}`).negative(ctx));
    }
  }
});

test('all quality scenarios defer before consuming shared work', async () => {
  const feature = features.find(value => value.feature_id === 'F56');
  const visits = [];
  for (const scenario of ['journey', 'negative', 'recovery']) {
    const cell = {locale:'en', theme:'light', width:390};
    const calls = [];
    const ctx = {
      cell,
      actor:async role => { calls.push(['actor',role]); return {actor_id:'test-reviewer'}; },
      signIn:async role => calls.push(['signIn',role]),
      page:{
        goto:async path => visits.push(path),
        waitFor:async () => {},
        evaluate:async fn => {
          if (fn.toString().includes('document.documentElement.lang')) {
            return {locale:cell.locale,direction:'ltr',theme:cell.theme,width:cell.width};
          }
        },
        click:async () => assert.fail('Deferred quality must not submit existing work'),
        fill:async () => assert.fail('Deferred quality must not invent findings'),
      },
      api:async () => assert.fail('Deferred quality must not manufacture source authority'),
    };
    await assert.rejects(feature[scenario](ctx), error => {
      assert.equal(error.code,'quality_lifecycle_deferred');
      assert.equal(error.actor_id,'test-reviewer');
      assert.equal(error.operation_id,undefined,'No quality operation has been performed');
      assert.match(error.message,/fresh accepted work.*current work revision/);
      return true;
    });
    assert.deepEqual(calls,[['actor','reviewer'],['signIn','reviewer']]);
  }
  assert.deepEqual(visits,Array(3).fill('/business/quality'));
});


test('all passport scenarios defer without inventing an issuance reference', async () => {
  const feature = features.find(value => value.feature_id === 'F60');
  for (const scenario of ['journey', 'negative', 'recovery']) {
    for (const locale of ['en', 'ar']) {
      const cell = {locale, theme:'light', width:390};
      const calls = [];
      const ctx = {
        cell,
        actor:async role => { calls.push(['actor',role]); return {actor_id:'test-buyer'}; },
        signIn:async role => calls.push(['signIn',role]),
        page:{
          goto:async path => calls.push(['goto',path]),
          waitFor:async () => {},
          evaluate:async fn => {
            if (fn.toString().includes('document.documentElement.lang')) {
              return {locale,direction:locale === 'ar' ? 'rtl' : 'ltr',theme:cell.theme,width:cell.width};
            }
          },
          click:async () => assert.fail('Deferred passport must not submit work'),
          fill:async () => assert.fail('Deferred passport must not invent source records'),
        },
        api:async () => assert.fail('Deferred passport must not issue or read an invented reference'),
      };
      await assert.rejects(feature[scenario](ctx), error => {
        assert.equal(error.code,'passport_lifecycle_deferred');
        assert.equal(error.actor_id,'test-buyer');
        assert.equal(error.operation_id,undefined,'No passport operation has been performed');
        assert.match(error.message,/released independent inspection.*issued passport reference/);
        return true;
      });
      assert.deepEqual(calls,[['actor','buyer'],['signIn','buyer'],['goto','/watches']]);
    }
  }
});
