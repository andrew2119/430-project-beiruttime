// Named regression tests, in order:
// 1. Every tab of one sample set opened together from the kit page, each link pressed right
//    after the last, ends signed in as its own account on its own start page, and no tab
//    shows an error or a refusal while the others sign in: each sample tab as its listed seed
//    account, and the Operator tab as the one account Identity's BT_DEMO_OPERATOR_EMAIL names.
//    The kit page never shows that account's address. After the Operator link's fixed cutoff
//    (the end of Tuesday 1 December 2026 in Beirut) the Operator tab instead shows only its plain
//    refusal and stays signed out, while every sample tab still signs in.
// 2. No sample link session has more power than a buyer who registered a moment ago on the
//    same stack: no operator power (seller approval, case decisions, the Operations area and
//    business records refused) and no business reach, except that each set's staff account
//    reaches its own sample business and is refused on every other business. The Operator
//    link session holds exactly what an ordinary sign-in of its own account holds, no more and
//    no less, and once its tab is closed that account's own password still signs it in, as
//    the same account with the same grants. After the cutoff that account's own password still
//    signs it in, with its operator power, though no Operator link session opens.
// 3. Two tabs in one window hold two different roles, and signing out in one leaves the
//    other signed in. A sample tab, signed in or out, never shows a password box: signed out,
//    the account page shows its own plain status instead of the password form.
// 4. A tab whose entry still fails after its quiet retries says only to reload it, keeps its
//    key in its own session storage, and once reloaded signs in on its own with no new link
//    from the kit; every tab forgets its key once it has signed in.
//
// Usage: BT_SAMPLE_TABS_KEY=<demo key> BT_SAMPLE_TABS_OPERATOR=<stand-in address>
//        BT_SAMPLE_TABS_OPERATOR_PASSWORD=<its password> node tests/native/n09/features/sample-tabs.mjs
//          --origin <web origin> --report <report.json> [--set click-test|demo]
// It needs the connected native stack with the demo seed applied (BT_DEMO_SEED, both sets) and the
// password-free switch on for this run only: the stack holds the SHA-256 of a key this run
// generated, and BT_SAMPLE_TABS_KEY holds the key itself. It also needs a stand-in operator: an
// ordinary account at the made-up address Identity's BT_DEMO_OPERATOR_EMAIL names, made that
// stack's operator, with a password made at run time (.github/ci/sample_tabs.py does both).
// BT_BROWSER (default /opt/google/chrome/chrome) names the installed browser. No key or password
// is printed: every report line passes through redact(), and no check reports an address or a
// cookie value. Every tab opens from the kit page's own links, exactly as the class opens them,
// and no password is typed into any page; the one ordinary buyer it registers gets a password
// made at run time, and the stand-in operator's ordinary sign-ins, made only to compare grants,
// are script calls in the kit tab that keep no cookie.
import {randomBytes, randomUUID} from 'node:crypto';
import {readFile, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
import {localBrowser} from './ctx.mjs';

const root = resolve(fileURLToPath(import.meta.url), '../../../../..');
const slotFormat = /^[A-Za-z0-9_-]{22}$/;
const keyFormat = /^[A-Za-z0-9_-]{32,200}$/;
const starts = {buyer: '/en/watches', staff: '/en/business'};
// Each listed role's start page, as web/features/identity/sample-accounts.ts names it.
const setStarts = {buyer: '/en/watches', seller: '/en/seller/verification', staff: '/en/business', operator: '/en/operations/dashboard', rival: '/en/watches'};
// The Operator link's fixed cutoff, OPERATOR_LINK_CUTOFF in services/identity/runtime/service_app/session_slots.py.
// A run that starts too close to it could see either answer from the Operator tab, so it stops.
const operatorLinkCutoff = Date.parse('2026-12-01T22:00:00Z');
const cutoffMargin = {before: 15 * 60 * 1000, after: 60 * 1000};
const pause = ms => new Promise(done => setTimeout(done, ms));
const secrets = [];
const redact = text => secrets.reduce((value, secret) => value.split(secret).join('[demo key]'), String(text));
const checks = [];
function check(name, ok, detail) {
  checks.push(ok ? {name, ok: true} : {name, ok: false, detail: redact(JSON.stringify(detail ?? null)).slice(0, 300)});
  if (!ok) throw new Error(`${name} failed`);
}
async function until(what, read, accept, timeout = 20000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    last = await read().catch(error => ({error: error.message}));
    if (accept(last)) return last;
    await pause(100);
  }
  check(what, false, last);
}
// Only the flags, never the value: a refresh cookie is a credential.
const flags = cookie => cookie ? {httpOnly: cookie.httpOnly, sameSite: cookie.sameSite, session: cookie.session, path: cookie.path, secure: cookie.secure} : null;

// In-page readers. They run inside the tab, so they only use what the page itself can see.
function landingState() {
  // A sample tab that stopped without signing in shows its card; any error shows as an alert.
  const alerts = [...document.querySelectorAll('[role="alert"]')].map(node => node.textContent.trim())
    .filter(text => text !== '');
  const notices = [...document.querySelectorAll('[data-sample-tab] [role="status"]')].map(node => node.textContent.trim());
  return {path: location.pathname, stopped: document.querySelector('[data-sample-tab]') !== null, alerts: alerts.length, notices};
}
function accountState(copy) {
  const page = document.querySelector('.bt-page');
  if (!page) return {state: 'loading'};
  const texts = selector => [...page.querySelectorAll(selector)].map(node => node.textContent.trim());
  if (texts('[role="status"]').includes(copy.loading)) return {state: 'restoring'};
  if (texts('[role="alert"] p').includes(copy.unavailable)) return {state: 'unavailable'};
  const passwordBox = document.querySelector('input[type="password"]') !== null;
  if (texts('button').includes(copy.signout)) return {state: 'in', email: page.querySelector('.account-stack bdi')?.textContent ?? null, passwordBox};
  // A signed-out sample tab shows its own status; the shared form there is a failure to report.
  if (page.querySelector('[data-sample-signed-out]')) return {state: 'out', passwordBox};
  if (page.querySelector('input[name="email"]')) return {state: 'form', passwordBox};
  return {state: 'loading'};
}
// Only yes or no: whether any of this tab's session storage holds the key, and which sample tab it holds.
function heldState(key) {
  const values = Object.keys(sessionStorage).map(name => sessionStorage.getItem(name) ?? '');
  return {key: values.some(value => value.includes(key)), tab: sessionStorage.getItem('bt-sample-tab')};
}
// A sample tab whose entry could not finish: its plain reload line, any alert, any password box.
function stuckState(reloadLine) {
  const texts = selector => [...document.querySelectorAll(selector)].map(node => node.textContent.trim());
  return {path: location.pathname, reload: texts('[role="status"]').includes(reloadLine),
    alerts: texts('[role="alert"]').filter(text => text !== '').length, passwordBox: document.querySelector('input[type="password"]') !== null};
}
// Installed before a page loads: the page's own calls to sample entry fail as if the network dropped them.
const entryOutage = `{const real = window.fetch; window.fetch = (input, init) =>
  String(input instanceof Request ? input.url : input).includes('/demo-entry/sessions') ? Promise.reject(new TypeError('offline')) : real(input, init);}`;
async function whoAmI() {
  const slot = sessionStorage.getItem('bt-session-slot');
  // The app's own refresh lock, so this check never races the tab's sign-in.
  return navigator.locks.request(slot ? `bt-refresh-v1:${slot}` : 'bt-refresh-v1', async () => {
    const response = await fetch('/api/web/v1/identity/v1/accounts/refresh', {method: 'POST', headers: slot ? {'X-BT-Session-Slot': slot} : {}});
    const body = response.ok ? await response.json() : null;
    return {status: response.status, email: body?.account?.email ?? null, id: body?.account?.id ?? null,
      grants: (body?.principal?.organization_grants ?? []).flatMap(grant => grant.roles), organizations: body?.principal?.organizations ?? []};
  });
}
// An ordinary registration that keeps no cookie, so the tab it runs in stays signed out.
async function registerBuyer(email, password, operation) {
  const response = await fetch('/api/web/v1/identity/v1/accounts/register', {method: 'POST', credentials: 'omit',
    headers: {'Content-Type': 'application/json', 'Idempotency-Key': operation}, body: JSON.stringify({email, password, display_name: 'Fresh buyer'})});
  const body = response.ok ? await response.json() : null;
  return {status: response.status, token: body?.access_token ?? null};
}
// An ordinary sign-in that keeps no cookie, so the tab it runs in stays signed out.
async function signInOrdinary(email, password) {
  const response = await fetch('/api/web/v1/identity/v1/accounts/login', {method: 'POST', credentials: 'omit',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email, password})});
  const body = response.ok ? await response.json() : null;
  return {status: response.status, token: body?.access_token ?? null, id: body?.account?.id ?? null};
}
// Every listed business, and whether each named one is marked as sample data, from the public directory.
async function businessFacts(ids) {
  const read = async path => {const response = await fetch(path, {credentials: 'omit'}); return response.ok ? response.json() : null;};
  const listed = await read('/api/web/v1/identity/v1/businesses');
  const samples = [];
  for (const id of ids) samples.push((await read(`/api/web/v1/identity/v1/businesses/${id}`))?.sample === true);
  return {listed: listed ? listed.items.map(item => item.id) : null, samples};
}
// What one sign-in may do: its principal as Identity reports it, and the status of each probe.
// A sample tab passes no token and takes its own from a refresh under the app's own lock; the
// fresh buyer passes the token its registration returned. Only statuses and grants come back.
async function reach(token, probes) {
  if (!token) {
    const slot = sessionStorage.getItem('bt-session-slot');
    token = await navigator.locks.request(`bt-refresh-v1:${slot}`, async () => {
      const response = await fetch('/api/web/v1/identity/v1/accounts/refresh', {method: 'POST', headers: {'X-BT-Session-Slot': slot}});
      return response.ok ? (await response.json()).access_token : null;
    });
  }
  const ask = (method, target) => fetch(target, {method, credentials: 'omit', body: method === 'POST' ? '{}' : undefined,
    headers: {Authorization: `Bearer ${token}`, ...(method === 'POST' ? {'Content-Type': 'application/json'} : {})}});
  const me = await ask('GET', '/api/web/v1/identity/v1/accounts/me');
  const principal = me.ok ? (await me.json()).principal : null;
  const answers = {};
  for (const [name, method, target] of probes) answers[name] = (await ask(method, target)).status;
  return {status: me.status, roles: principal?.roles ?? null, permissions: principal?.permissions ?? null, organizations: principal?.organizations ?? null,
    grants: (principal?.organization_grants ?? []).map(grant => ({organization: grant.organization_id, roles: grant.roles})), answers};
}

async function main() {
  const {values} = parseArgs({options: {origin: {type: 'string'}, report: {type: 'string'}, set: {type: 'string', default: 'click-test'}}});
  if (!values.origin || !values.report) throw new Error('Use --origin and --report');
  const key = process.env.BT_SAMPLE_TABS_KEY ?? '';
  if (!keyFormat.test(key)) throw new Error('Set BT_SAMPLE_TABS_KEY to this run\'s demo key');
  secrets.push(key, encodeURIComponent(key));
  const operator = process.env.BT_SAMPLE_TABS_OPERATOR ?? '', operatorPassword = process.env.BT_SAMPLE_TABS_OPERATOR_PASSWORD ?? '';
  if (!/^[a-z0-9.-]+@example\.test$/.test(operator) || operatorPassword.length < 12) {
    throw new Error('Set BT_SAMPLE_TABS_OPERATOR and BT_SAMPLE_TABS_OPERATOR_PASSWORD to this run\'s stand-in operator');
  }
  secrets.push(operatorPassword);
  const origin = new URL(values.origin).origin;
  const set = values.set;
  if (!['demo', 'click-test'].includes(set)) throw new Error('Use --set demo or --set click-test');
  const startedAt = Date.now();
  if (startedAt >= operatorLinkCutoff - cutoffMargin.before && startedAt < operatorLinkCutoff + cutoffMargin.after) {
    throw new Error('This run is too close to the Operator link cutoff; run it again after it');
  }
  const operatorEnded = startedAt >= operatorLinkCutoff;
  const copy = JSON.parse(await readFile(join(root, 'web/features/identity/en.json'), 'utf8'));
  // After the cutoff, the one stop this check expects: the Operator tab's plain refusal, and nothing else.
  const refusedOperator = state => operatorEnded && state.role === 'operator' && state.stopped && state.alerts === 0
    && state.notices.length === 1 && state.notices[0] === copy.operator_link_unavailable;
  const list = JSON.parse(await readFile(join(root, 'packages/contracts-identity/accounts/sample-accounts.v1.json'), 'utf8'));
  const inSet = list.accounts.filter(entry => entry.set === set);
  if (inSet.some(entry => entry.role === 'operator')) throw new Error('The sample list must name no operator');
  // Every tab the kit opens: one per listed sample account, then the Operator tab, whose account
  // (and so its id) only Identity knows; the tab's own check below records that id.
  const kitTabs = [...inSet.map(entry => ({role: entry.role, email: entry.email, id: entry.account_id})), {role: 'operator', email: operator, id: null}];
  const accounts = Object.fromEntries(Object.keys(starts).map(role => [role, inSet.find(entry => entry.role === role)]));
  for (const [role, account] of Object.entries(accounts)) if (!account) throw new Error(`The sample list names no ${role} account in set ${set}`);
  for (const entry of kitTabs) if (!setStarts[entry.role]) throw new Error(`No start page is known for the ${entry.role} tab`);
  const cell = {width: 1440, height: 900, dpr: 1, mobile: false, touch: false, locale: 'en', theme: 'light'};
  const session = await localBrowser({browserPath: process.env.BT_BROWSER || '/opt/google/chrome/chrome', origin, cell});
  let ok = false;
  try {
    const kit = session.page;
    const browser = (method, params) => session.call(method, params, null);
    // Only ids and types: a tab's address can still hold the key before the page strips it.
    const targets = async () => (await browser('Target.getTargets', {})).targetInfos.map(info => ({targetId: info.targetId, type: info.type}));
    const windowOf = async targetId => (await browser('Browser.getWindowForTarget', {targetId})).windowId;
    const cookies = async () => (await session.call('Network.getCookies', {urls: [origin]})).cookies;

    // The kit page is opened the way the class opens it: one link naming its set, key in the fragment.
    const opening = await session.call('Page.navigate', {url: `${origin}/en/sample-tabs#set=${set}&k=${key}`});
    check('kit page opens', !opening.errorText);
    const links = `[data-sample-kit="${set}"] a[target="_blank"]`;
    await kit.waitFor(links, {timeout: 20000});
    check('kit page shows one link per listed sample account of its set, and one Operator link',
      await kit.evaluate(selector => document.querySelectorAll(selector).length, links) === kitTabs.length);
    check('kit page never shows the Operator account\'s address', await kit.evaluate(address => !document.body.textContent.includes(address), operator));
    check('kit page strips the key from its address', await kit.evaluate(() => location.hash === '' && location.pathname === '/en/sample-tabs'));
    const kitHeld = await kit.evaluate(heldState, key);
    check('the kit tab keeps no key and holds no sample tab', !kitHeld.key && kitHeld.tab === null);
    const {targetInfo: {targetId: kitTarget}} = await session.call('Target.getTargetInfo', {});
    const kitWindow = await windowOf(kitTarget);
    // The id of the one page a click just opened, looked for every 10 ms so no tab waits on another.
    const newPage = async before => {
      const end = Date.now() + 5000;
      while (Date.now() < end) {
        const fresh = (await targets()).find(info => info.type === 'page' && !before.has(info.targetId));
        if (fresh) return fresh.targetId;
        await pause(10);
      }
      return null;
    };

    // Regression 1: all tabs of the set opened together. Each link is pressed right after the
    // last, with no wait for any tab to sign in, so their entries reach the site together.
    const together = {};
    for (const entry of kitTabs) {
      const before = new Set((await targets()).map(info => info.targetId));
      await session.call('Page.bringToFront');
      await kit.click(`${links}[href*="#set=${set}&role=${entry.role}&k="]`);
      together[entry.role] = await newPage(before);
      check(`opened together: ${entry.role} tab opens from the kit page`, together[entry.role] !== null);
    }
    const group = {};
    for (const entry of kitTabs) {
      check(`opened together: ${entry.role} tab opens in the same window as the kit page`, await windowOf(together[entry.role]) === kitWindow);
      group[entry.role] = await session.attach(together[entry.role]);
    }
    // Polled from the moment the last link is pressed: any error or refusal fails at once.
    const landed = await until('opened together: every tab signs in and lands on its start page',
      async () => {
        const states = [];
        for (const entry of kitTabs) states.push({role: entry.role, ...await group[entry.role].evaluate(landingState)});
        return states;
      },
      states => Array.isArray(states) && (states.some(state => (state.stopped && !refusedOperator(state)) || state.alerts > 0)
        || states.every(state => refusedOperator(state) || state.path === setStarts[state.role])), 45000);
    check(operatorEnded ? 'opened together: no sample tab shows an error or a refusal' : 'opened together: no tab shows an error or a refusal',
      landed.every(state => (!state.stopped || refusedOperator(state)) && state.alerts === 0),
      landed.map(({role, stopped, alerts}) => ({role, stopped, alerts})));
    let operatorId = null;
    for (const entry of kitTabs) {
      const who = await group[entry.role].evaluate(whoAmI);
      if (entry.role === 'operator' && operatorEnded) {
        check('after the Operator link cutoff: the Operator tab shows only its plain refusal and is signed in as no one',
          refusedOperator(landed.find(state => state.role === 'operator')) && who.status === 401 && who.id === null, {status: who.status});
      } else if (entry.role === 'operator') {
        operatorId = who.id;
        check('opened together: the Operator tab is signed in as the account BT_DEMO_OPERATOR_EMAIL names',
          who.status === 200 && who.email === operator && Boolean(who.id) && !list.accounts.some(listed => listed.account_id === who.id),
          {status: who.status, email: who.email === operator});
      } else {
        check(`opened together: ${entry.role} tab is signed in as the listed ${entry.role} seed account`,
          who.status === 200 && who.email === entry.email && who.id === entry.id,
          {status: who.status, email: who.email === entry.email, id: who.id === entry.id});
      }
    }
    const groupSlots = [];
    for (const entry of kitTabs) groupSlots.push(await group[entry.role].evaluate(() => sessionStorage.getItem('bt-session-slot')));
    check('opened together: each tab holds its own slot', groupSlots.every(slot => slotFormat.test(slot)) && new Set(groupSlots).size === kitTabs.length,
      groupSlots.map(slot => slotFormat.test(slot)));
    for (const entry of kitTabs) {
      const held = await group[entry.role].evaluate(heldState, key);
      if (entry.role === 'operator' && operatorEnded) {
        // A tab that was refused keeps its key, as any tab that is not ready does, so only its tab is checked.
        check('after the Operator link cutoff: the Operator tab holds only its own set and role', held.tab === `${set}:operator`,
          {tab: held.tab === `${set}:operator`});
        continue;
      }
      check(`opened together: ${entry.role} tab forgets its key once signed in and holds only its own set and role`,
        !held.key && held.tab === `${set}:${entry.role}`, {key: held.key, tab: held.tab === `${set}:${entry.role}`});
    }

    // Regression 2: no sample link session may do more than a buyer who registered a moment ago on
    // this same stack. The seed's only addition is each set's staff account's membership of its own
    // sample business, so the other set's staff tab opens too, from that set's own kit page. The
    // Operator link session is compared with an ordinary sign-in of its own account instead.
    const other = set === 'demo' ? 'click-test' : 'demo';
    const otherStaff = list.accounts.find(entry => entry.set === other && entry.role === 'staff');
    if (!otherStaff) throw new Error(`The sample list names no staff account in set ${other}`);
    const password = randomBytes(24).toString('base64url');
    secrets.push(password);
    const fresh = await kit.evaluate(registerBuyer, `fresh-buyer-${randomUUID()}@example.test`, password, randomUUID());
    if (fresh.token) secrets.push(fresh.token);
    check('no more power: a fresh buyer registers in an ordinary tab', fresh.status === 201 && Boolean(fresh.token), {status: fresh.status});
    const {targetId: otherKitTarget} = await browser('Target.createTarget', {url: `${origin}/en/sample-tabs#set=${other}&k=${key}`});
    const otherKit = await session.attach(otherKitTarget);
    const otherLink = `[data-sample-kit="${other}"] a[target="_blank"][href*="#set=${other}&role=staff&k="]`;
    await otherKit.waitFor(otherLink, {timeout: 20000});
    const beforeOther = new Set((await targets()).map(info => info.targetId));
    await otherKit.front();
    await otherKit.click(otherLink);
    const otherTarget = await newPage(beforeOther);
    check(`no more power: the ${other} staff tab opens from its own kit page`, otherTarget !== null);
    const otherTab = await session.attach(otherTarget);
    await until(`no more power: the ${other} staff tab signs in and lands on its start page`,
      () => otherTab.evaluate(() => location.pathname), path => path === setStarts.staff, 30000);
    const ownStaff = await group.staff.evaluate(whoAmI), farStaff = await otherTab.evaluate(whoAmI);
    check(`no more power: the ${other} staff tab is the listed ${other} staff seed account`,
      farStaff.status === 200 && farStaff.email === otherStaff.email && farStaff.id === otherStaff.account_id, {status: farStaff.status, email: farStaff.email === otherStaff.email});
    const home = {[set]: ownStaff.organizations[0], [other]: farStaff.organizations[0]};
    check('no more power: each staff account belongs to exactly one business, and the two differ',
      ownStaff.organizations.length === 1 && farStaff.organizations.length === 1 && home[set] !== home[other],
      {[set]: ownStaff.organizations.length, [other]: farStaff.organizations.length});
    const facts = await kit.evaluate(businessFacts, [home[set], home[other]]);
    check('no more power: both staff businesses are marked as sample data', Array.isArray(facts.listed) && facts.samples.every(Boolean), facts.samples);

    const api = (service, rest) => `/api/web/v1/${service}/${rest}`;
    const madeUp = randomUUID();
    const businesses = [[`the ${set} sample business`, home[set]], [`the ${other} sample business`, home[other]], ['a made-up business', madeUp],
      ...facts.listed.filter(id => id !== home[set] && id !== home[other]).map((id, index) => [`listed business ${index + 1}`, id])];
    const probes = [
      ['own private listings', 'GET', api('catalog', 'v1/seller/listings')],
      ['seller approval queue', 'GET', api('identity', 'v1/private-reviews')],
      ['seller approval decision', 'POST', api('identity', `v1/private-reviews/${madeUp}/verdict`)],
      ['case queue', 'GET', api('trust', 'v1/moderation/cases')],
      ['case decision', 'POST', api('trust', `v1/moderation/cases/${madeUp}/decisions`)],
      ['Operations queues', 'GET', api('communications', 'v1/operator-workspace/queues')],
      ['business records', 'GET', api('identity', 'v1/businesses/manage/records')],
      ['staff membership grant', 'POST', api('identity', 'v1/memberships')],
      ...businesses.map(([name, id]) => [`stock of ${name}`, 'GET', api('catalog', `v1/seller/listings?organization_id=${id}`)]),
    ];
    const buyer = await kit.evaluate(reach, fresh.token, probes);
    check('no more power: the fresh buyer holds a plain buyer\'s power', buyer.status === 200 && JSON.stringify(buyer.roles) === '["buyer"]'
      && buyer.permissions?.length === 0 && buyer.organizations?.length === 0 && buyer.grants.length === 0,
      {status: buyer.status, roles: buyer.roles, permissions: buyer.permissions, organizations: buyer.organizations?.length});
    check('no more power: the fresh buyer reads its own listings and is refused every operator and business probe',
      buyer.answers['own private listings'] === 200 && probes.slice(1).every(([name]) => buyer.answers[name] === 403), buyer.answers);
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const signIns = [...inSet.map(entry => [entry, group[entry.role]]), [otherStaff, otherTab]];
    for (const [entry, tab] of signIns) {
      const name = `${entry.set} ${entry.role}`;
      const power = await tab.evaluate(reach, null, probes);
      // The seed's staff grant is the one difference, and only for that set's own business.
      const own = entry.role === 'staff' ? home[entry.set] : null;
      const held = own
        ? same(power.roles, [...new Set([...buyer.roles, 'dealer'])].sort()) && same(power.organizations, [own])
          && power.grants.length === 1 && power.grants[0].organization === own && same(power.grants[0].roles, ['dealer'])
        : same(power.roles, buyer.roles) && same(power.organizations, buyer.organizations) && same(power.grants, buyer.grants);
      check(own ? `no more power: the ${name} link session holds a fresh buyer's power plus its own sample business only`
        : `no more power: the ${name} link session holds exactly a fresh buyer's power`,
        power.status === 200 && held && same(power.permissions, buyer.permissions),
        {status: power.status, roles: power.roles, permissions: power.permissions, organizations: power.organizations?.length, grants: power.grants.map(grant => grant.roles)});
      const expected = {...buyer.answers};
      if (own) expected[`stock of the ${entry.set} sample business`] = 200;
      check(own ? `no more power: the ${name} link session reaches its own sample business and is refused everything else a fresh buyer is refused`
        : `no more power: the ${name} link session gets every answer a fresh buyer gets`,
        probes.every(([probe]) => power.answers[probe] === expected[probe]), power.answers);
    }
    const ordinary = await kit.evaluate(signInOrdinary, operator, operatorPassword);
    if (ordinary.token) secrets.push(ordinary.token);
    if (operatorEnded) {
      // No Operator link session opened, so the account's own sign-in is the one to compare with later.
      check('operator: the stand-in operator still signs in ordinarily after the Operator link cutoff', ordinary.status === 200 && Boolean(ordinary.id),
        {status: ordinary.status});
      operatorId = ordinary.id;
    } else {
      check('operator: the stand-in operator signs in ordinarily as the Operator tab\'s account', ordinary.status === 200 && ordinary.id === operatorId,
        {status: ordinary.status, same: ordinary.id === operatorId});
    }
    const own = await kit.evaluate(reach, ordinary.token, probes);
    check('operator: an ordinary sign-in of that account holds operator power', own.status === 200 && Boolean(own.permissions?.includes('identity.businesses.manage')),
      {status: own.status, roles: own.roles});
    if (!operatorEnded) {
      const linked = await group.operator.evaluate(reach, null, probes);
      check('operator: the Operator link session holds exactly the grants of an ordinary sign-in of its own account',
        linked.status === 200 && same(linked.roles, own.roles) && same(linked.permissions, own.permissions) && same(linked.organizations, own.organizations)
          && same(linked.grants, own.grants), {status: linked.status, roles: linked.roles, permissions: linked.permissions?.length, organizations: linked.organizations?.length});
      check('operator: the Operator link session gets every answer an ordinary sign-in of its own account gets',
        probes.every(([probe]) => linked.answers[probe] === own.answers[probe]), {linked: linked.answers, ordinary: own.answers});
    }
    for (const targetId of [otherTarget, otherKitTarget, ...kitTabs.map(entry => together[entry.role])]) await browser('Target.closeTarget', {targetId});
    // The link changed nothing about the account: its own password still signs it in, with the same grants.
    const later = await kit.evaluate(signInOrdinary, operator, operatorPassword);
    if (later.token) secrets.push(later.token);
    const laterPower = later.token ? await kit.evaluate(reach, later.token, []) : null;
    check('operator: once the Operator tab is closed, the account\'s own password still signs it in, as the same account with the same grants',
      later.status === 200 && later.id === operatorId && laterPower?.status === 200 && same(laterPower.roles, own.roles)
        && same(laterPower.permissions, own.permissions) && same(laterPower.grants, own.grants), {status: later.status, same: later.id === operatorId});

    // Regression 3: two tabs, two roles, and signing out in one leaves the other signed in.
    const tabs = {};
    for (const role of Object.keys(accounts)) {
      const before = new Set((await targets()).map(info => info.targetId));
      await session.call('Page.bringToFront');
      await kit.click(`${links}[href*="#set=${set}&role=${role}&k="]`);
      const opened = await until(`${role} tab opens from the kit page`,
        async () => (await targets()).find(info => info.type === 'page' && !before.has(info.targetId)), Boolean);
      check(`${role} tab opens in the same window as the kit page`, await windowOf(opened.targetId) === kitWindow);
      const tab = tabs[role] = await session.attach(opened.targetId);
      await tab.front();
      await until(`${role} tab signs in without a password and lands on its start page`,
        () => tab.evaluate(() => location.pathname), path => path === starts[role]);
    }

    const slots = {};
    for (const role of Object.keys(accounts)) slots[role] = await tabs[role].evaluate(() => sessionStorage.getItem('bt-session-slot'));
    check('each sample tab holds its own slot', Object.values(slots).every(slot => slotFormat.test(slot)) && slots.buyer !== slots.staff,
      Object.values(slots).map(slot => slotFormat.test(slot)));
    check('the kit tab holds no slot', await kit.evaluate(() => sessionStorage.getItem('bt-session-slot')) === null);
    const jar = await cookies();
    for (const role of Object.keys(accounts)) {
      const cookie = jar.find(item => item.name === `bt_refresh_s_${slots[role]}`);
      check(`${role} slot cookie is HttpOnly, SameSite Strict and ends with the browser session`,
        cookie?.httpOnly === true && cookie.sameSite === 'Strict' && cookie.session === true && cookie.path === '/', flags(cookie));
    }
    check('no shared sign-in cookie was created', !jar.some(item => item.name === 'bt_refresh'));

    const buyerTab = await tabs.buyer.evaluate(whoAmI), staffTab = await tabs.staff.evaluate(whoAmI);
    check('buyer tab is the listed buyer seed account', buyerTab.status === 200 && buyerTab.email === accounts.buyer.email && buyerTab.id === accounts.buyer.account_id, {status: buyerTab.status, email: buyerTab.email});
    check('staff tab is the listed staff seed account', staffTab.status === 200 && staffTab.email === accounts.staff.email && staffTab.id === accounts.staff.account_id, {status: staffTab.status, email: staffTab.email});
    check('the two tabs hold two different roles', staffTab.grants.includes('dealer') && buyerTab.grants.length === 0, {buyer: buyerTab.grants, staff: staffTab.grants});

    for (const [role, account] of Object.entries(accounts)) {
      await tabs[role].front();
      await tabs[role].goto('/en/account');
      const shown = await until(`${role} tab shows its own account`, () => tabs[role].evaluate(accountState, copy), state => state.state === 'in' && state.email === account.email);
      check(`${role} tab offers no password change`, shown.passwordBox === false);
    }

    await tabs.staff.front();
    await tabs.staff.evaluate(text => [...document.querySelectorAll('.bt-page button')].find(node => node.textContent.trim() === text).setAttribute('data-sample-signout', ''), copy.signout);
    await tabs.staff.click('[data-sample-signout]');
    await until('staff tab signs out and shows its own status with no password box', () => tabs.staff.evaluate(accountState, copy),
      state => state.state === 'out' && !state.passwordBox);

    for (const role of Object.keys(accounts)) {await tabs[role].front(); await tabs[role].reload();}
    await until('after a reload the buyer tab is still signed in', () => tabs.buyer.evaluate(accountState, copy), state => state.state === 'in' && state.email === accounts.buyer.email);
    await until('after a reload the staff tab stays signed out, with its own status and no password box', () => tabs.staff.evaluate(accountState, copy),
      state => state.state === 'out' && !state.passwordBox);
    for (const role of Object.keys(accounts)) check(`${role} tab keeps its slot across the reload`, await tabs[role].evaluate(() => sessionStorage.getItem('bt-session-slot')) === slots[role]);
    const after = await cookies();
    check('only the signed-out slot lost its cookie',
      after.some(item => item.name === `bt_refresh_s_${slots.buyer}`) && !after.some(item => item.name === `bt_refresh_s_${slots.staff}`));
    const still = await tabs.buyer.evaluate(whoAmI), gone = await tabs.staff.evaluate(whoAmI);
    check('the buyer sign-in still refreshes and the staff one does not', still.status === 200 && still.email === accounts.buyer.email && gone.status === 401, {buyer: still.status, staff: gone.status});

    // Regression 4: the signed-out staff tab opens its link again while its own calls to sample
    // entry fail, so its quiet retries run out; then the tab is reloaded with entry working again.
    const retry = tabs.staff;
    await retry.front();
    const {identifier: outage} = await retry.call('Page.addScriptToEvaluateOnNewDocument', {source: entryOutage});
    const reopened = await retry.call('Page.navigate', {url: `${origin}/en/sample-tabs#set=${set}&role=staff&k=${key}`});
    check('reload: the staff tab opens its link again', !reopened.errorText);
    const stuck = await until('reload: a tab whose entry keeps failing says only to reload it',
      () => retry.evaluate(stuckState, copy.sampleReload), state => state.reload || state.alerts > 0 || state.passwordBox, 40000);
    check('reload: the failed tab shows no error and no password box', stuck.path === '/en/sample-tabs' && stuck.alerts === 0 && !stuck.passwordBox, stuck);
    check('reload: the failed tab still holds its key in its own session storage', (await retry.evaluate(heldState, key)).key === true);
    await retry.call('Page.removeScriptToEvaluateOnNewDocument', {identifier: outage});
    // The browser's own reload: the address holds no fragment any more, so nothing from the kit is reused.
    await retry.call('Page.reload', {});
    await until('reload: the reloaded tab signs in on its own and lands on its start page',
      () => retry.evaluate(() => location.pathname), path => path === starts.staff, 30000);
    const landedAgain = await retry.evaluate(landingState);
    check('reload: the reloaded tab shows no error', landedAgain.alerts === 0 && !landedAgain.stopped, landedAgain);
    const back = await retry.evaluate(whoAmI);
    check('reload: the reloaded tab is the listed staff seed account', back.status === 200 && back.email === accounts.staff.email && back.id === accounts.staff.account_id,
      {status: back.status, email: back.email === accounts.staff.email});
    check('reload: the tab forgets its key once signed in', (await retry.evaluate(heldState, key)).key === false);
    ok = true;
  } catch (error) {
    if (!checks.some(item => !item.ok)) checks.push({name: 'run', ok: false, detail: redact(error.message).slice(0, 300)});
  } finally {
    await session.close().catch(() => {});
    await writeFile(values.report, JSON.stringify({ok, set, checks}, null, 2) + '\n');
  }
  for (const item of checks) console.log(`${item.ok ? 'PASS' : 'FAIL'} ${item.name}${item.ok ? '' : ` ${item.detail}`}`);
  if (!ok) process.exitCode = 1;
}

await main();
