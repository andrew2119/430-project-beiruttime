import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { test } from 'node:test';
import { cssDeclarations, inspectSource, LAYER_SLOTS } from './check-ui-rules.mjs';
import { matchSelector, tokenCascade } from './token-cascade.mjs';

const read = file => readFileSync(new URL(`../../${file}`, import.meta.url), 'utf8');
const tokens = read('web/styles/tokens.css');
const entries = cssDeclarations(tokens);
const normalize = value => value.replace(/\s+/g, ' ').trim();
function expand(value, env, seen = new Set()) {
  return normalize(value.replace(/var\(\s*(--[\w-]+)\s*\)/g, (original, name) => {
    if (!(name in env)) return original;
    assert.ok(!seen.has(name), `Cyclic token: ${name}`);
    return expand(env[name], env, new Set([...seen, name]));
  }));
}
const environment = list => Object.fromEntries(list.map(entry => [entry.prop, entry.value]));
const rootEntries = entries.filter(entry => entry.context.length === 1 && (/^@theme/.test(entry.context[0]) || /(?:^|,)\s*:root(?:\s*,|$)/.test(entry.context[0])));

// Lock all 271 retained pre-migration declarations; two unused external-mark
// values were retired. Cover selector/media context, order and expanded value.
// It is not a browser cascade, font-metric or screenshot-parity certificate.
test('all retained token spellings keep their exact expanded declaration facts', () => {
  const facts = entries.filter(entry => !entry.prop.startsWith('--bt-')).map(entry => {
    const same = entries.filter(candidate => candidate.context.join('\n') === entry.context.join('\n'));
    const env = environment([...rootEntries, ...same]);
    return [entry.context.map(normalize), entry.prop, expand(entry.value, env)];
  });
  assert.equal(facts.length, 271);
  assert.equal(createHash('sha256').update(JSON.stringify(facts)).digest('hex'), '441375f909fc802efdd6fa2be726a04d972d7c361fe920c4195788d675e3d497');
});

const compute = tokenCascade(tokens);
const element = (theme, classes = [], parent = null, lang) => ({
  tag: parent ? 'div' : 'html', parent, classes,
  attrs: {...(theme ? {'data-theme':theme} : {}), ...(lang ? {lang} : {})},
});
const opposite = theme => theme === 'light' ? 'dark' : 'light';
const themeEnvironment = theme => compute(element(theme));

test('every canonical reference exists and every declaration graph is acyclic', () => {
  const declared = new Set(entries.map(entry => entry.prop));
  for (const entry of entries) {
    for (const [, name] of entry.value.matchAll(/var\(\s*(--[\w-]+)/g)) assert.ok(declared.has(name) || ['--font-lexend-deca', '--font-arabic'].includes(name), `${entry.prop}: missing ${name}`);
    const scoped = entries.filter(candidate => candidate.context.join('\n') === entry.context.join('\n'));
    expand(entry.value, environment([...rootEntries, ...scoped]));
  }
  assert.ok(entries.filter(entry => entry.prop.startsWith('--bt-')).length > 150);
  assert.ok(entries.filter(entry => entry.context.some(part => /^@theme/.test(part))).every(entry => entry.context.length === 1));
});

test('canonical roles survive the real header scope under either opposite-theme boundary', () => {
  for (const theme of ['light', 'dark']) for (const width of [390, 850, 851, 1440]) {
    const direct = compute(element(theme), width);
    const boundary = element(theme, [], element(opposite(theme)));
    for (const host of [boundary, element(undefined, [], boundary), element(undefined, ['hx-sys'], boundary)]) {
      const actual = compute(host, width);
      for (const name of Object.keys(direct).filter(name => name.startsWith('--bt-'))) assert.equal(actual[name], direct[name], `${theme}/${width}/${host.classes}: ${name}`);
      assert.equal(actual['color-scheme'], theme);
    }
  }
  const scopes = entries.filter(entry => entry.context.some(part => /\.hx-sys|\.pg-(?:shell|boot-frame|mobile-drawer)/.test(part)));
  assert.ok(scopes.every(entry => !entry.prop.startsWith('--bt-')), 'Legacy scopes may only rebind legacy properties.');
  const broken = tokenCascade(tokens.replace('.hx-sys {', '.hx-sys { --bt-glass-milk: color-mix(in oklab, var(--bt-card) 64%, transparent);'));
  const header = element(undefined, ['hx-sys'], element('dark', [], element('light')));
  assert.notEqual(broken(header)['--bt-glass-milk'], compute(header)['--bt-glass-milk'], 'A local canonical override must be observable, not filtered out by the model.');
});

test('the bounded cascade model applies specificity, source order and computed inheritance', () => {
  const root = element('light');
  const frame = element('light', ['frame'], root);
  assert.deepEqual(matchSelector(':where(.frame)', frame), [0,0,0]);
  assert.deepEqual(matchSelector(':is(.frame)', frame), [0,1,0]);
  assert.deepEqual(matchSelector(':root[data-theme="light"] .frame', frame), [0,3,0]);
  const source = ':root {--seed:parent;--derived:var(--seed);} [data-theme] {--depth:desktop;} :where(.frame) {--seed:child;--depth:phone;}';
  assert.equal(tokenCascade(source)(frame)['--depth'], 'desktop');
  assert.equal(tokenCascade(source.replace(':where(.frame)', ':is(.frame)'))(frame)['--depth'], 'phone');
  assert.equal(tokenCascade(source)(frame)['--derived'], 'parent');
  assert.throws(() => tokenCascade('@supports (display:grid) {.frame {--depth:phone;}}')(frame), /Unsupported token condition/);
  assert.throws(() => matchSelector('.root > .frame', frame), /Unsupported token selector/);
});

test('phone frame token rebinding wins on themed hosts and under separate theme wrappers', () => {
  const classes = ['bt-shell', 'bt-first-frame', 'bt-navigation-sheet'];
  for (const theme of ['light', 'dark']) for (const name of classes) for (const width of [390, 850, 851, 1440]) {
    const root = element(opposite(theme));
    const hosts = [element(theme, [name], root), element(undefined, [name], element(theme, [], root))];
    const direct = compute(element(theme), width);
    for (const host of hosts) {
      const actual = compute(host, width), phone = width <= 850;
      assert.equal(actual['--bt-shadow-frame'], direct[phone ? '--bt-phone-shadow-frame' : '--bt-shadow-frame'], `${theme}/${name}/${width}`);
      assert.equal(actual['--bt-radius-navigation'], phone ? '20px' : '22px');
      assert.equal(actual['--bt-radius-frame'], phone ? '20px' : '24px');
    }
  }
  const broken = tokenCascade(tokens.replace(':is(.bt-shell, .bt-first-frame, .bt-navigation-sheet)', ':where(.bt-shell, .bt-first-frame, .bt-navigation-sheet)'));
  const host = element('dark', ['bt-shell'], element('light'));
  assert.notEqual(broken(host, 850)['--bt-shadow-frame'], compute(host, 850)['--bt-shadow-frame'], 'A zero-specificity regression must lose to the host theme.');
});

function luminance(colour) {
  if (/^#[\da-f]{6}$/i.test(colour)) {
    const rgb = [1, 3, 5].map(at => parseInt(colour.slice(at, at + 2), 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  }
  const match = /^ok(lch|lab)\(([^)]+)\)$/.exec(colour);
  assert.ok(match, `Unsupported contrast input: ${colour}`);
  const parts = match[2].split(/\s+/);
  const lightness = parseFloat(parts[0]) / (parts[0].endsWith('%') ? 100 : 1);
  let a = Number(parts[1]), b = Number(parts[2]);
  if (match[1] === 'lch') { a = Number(parts[1]) * Math.cos(Number(parts[2]) * Math.PI / 180); b = Number(parts[1]) * Math.sin(Number(parts[2]) * Math.PI / 180); }
  const l = (lightness + .3963377774 * a + .2158037573 * b) ** 3;
  const m = (lightness - .1055613458 * a - .0638541728 * b) ** 3;
  const s = (lightness - .0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = value => Math.min(1, Math.max(0, value));
  const red = clamp(4.0767416621 * l - 3.3077115913 * m + .2309699292 * s);
  const green = clamp(-1.2684380046 * l + 2.6097574011 * m - .3413193965 * s);
  const blue = clamp(-.0041960863 * l - .7034186147 * m + 1.707614701 * s);
  return red * .2126 + green * .7152 + blue * .0722;
}
function contrast(first, second) {
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}
test('opaque semantic ink/fill pairs clear their numerical contrast floor', () => {
  assert.ok(Math.abs(contrast('#ffffff', '#000000') - 21) < 1e-6);
  for (const theme of ['light', 'dark']) {
    const env = themeEnvironment(theme);
    const pairs = [['foreground', 'background'], ['card-foreground', 'card'], ['popover-foreground', 'popover'], ['muted-foreground', 'card'], ['muted-foreground', 'muted'], ['primary-foreground', 'primary'], ['destructive-foreground', 'destructive'], ['primary-ink', 'card'], ['destructive-ink', 'card'], ['success-ink', 'muted']];
    for (const [ink, fill] of pairs) assert.ok(contrast(env[`--bt-${ink}`], env[`--bt-${fill}`]) >= 4.5, `${theme}: ${ink}/${fill}`);
    for (const fill of ['background', 'card', 'muted']) assert.ok(contrast(env['--bt-ring'], env[`--bt-${fill}`]) >= 3, `${theme}: focus/${fill}`);
    assert.ok(contrast(env['--bt-muted-foreground'], env['--bt-muted']) >= 4.7, `${theme}: canonical muted pair needs a clear margin`);
    assert.equal(env['--muted-foreground'], env['--bt-compat-muted-foreground']);
    assert.equal(env['--color-muted-foreground'], env['--muted-foreground'], 'Existing utility exports must retain compatibility ink.');
  }
  const dark = themeEnvironment('dark');
  assert.equal(dark['--muted-foreground'], 'oklch(65% 0 0)');
  assert.ok(contrast(dark['--muted-foreground'], dark['--bt-muted']) < 4.5, 'Known legacy debt is not silently retuned.');
  const broken = tokenCascade(tokens.replace('--bt-muted-foreground: oklch(67% 0 0)', '--bt-muted-foreground: oklch(65% 0 0)'))(element('dark'));
  assert.ok(contrast(broken['--bt-muted-foreground'], broken['--bt-muted']) < 4.5, 'The prior canonical failure must be observable.');
});

test('scales, painted controls, targets, window sizes and layers have one shared contract', () => {
  const env = themeEnvironment('light');
  for (const [step, value] of [[1,4], [2,8], [3,12], [4,16], [5,20], [6,24], [8,32], [10,40], [12,48], [16,64]]) assert.equal(env[`--bt-space-${step}`], `${value}px`);
  assert.equal(env['--bt-touch-target'], '44px');
  assert.equal(env['--bt-phone-control'], '36px');
  assert.equal(env['--bt-phone-chip'], '32px');
  assert.equal(env['--bt-window-read'], '44rem');
  assert.equal(env['--bt-window-wide'], '60rem');
  const phone = entries.filter(entry => entry.context[0] === '@media (max-width: 850px)' && entry.context.at(-1) === ':is(.bt-shell, .bt-first-frame, .bt-navigation-sheet)');
  assert.equal(environment(phone)['--bt-shadow-frame'], 'var(--bt-phone-shadow-frame)');
  assert.equal(environment(phone)['--bt-radius-navigation'], '20px');
  assert.equal(environment(phone)['--bt-radius-frame'], '20px');
  const layers = LAYER_SLOTS.filter(name => name.startsWith('--bt-')).map(name => Number(env[name]));
  assert.equal(layers.length, 9);
  assert.ok(layers.every((value, index) => Number.isSafeInteger(value) && (index === 0 || value > layers[index - 1])));
  assert.equal(env['--z-avatar'], env['--bt-layer-content']);
  assert.equal(env['--z-loading-overlay'], env['--bt-layer-loading']);
  assert.equal(env['--z-skip-link'], env['--bt-layer-skip']);
});

test('legacy computed token values match the fixed main-byte source-cascade snapshot', () => {
  const legacy = [...new Set(entries.map(entry => entry.prop).filter(name => !name.startsWith('--bt-')))].sort();
  const resolve = tokenCascade(tokens + '\n' + read('web/styles/ar.css'));
  const facts = [];
  for (const theme of ['light', 'dark']) for (const lang of ['en', 'ar']) for (const width of [390,850,851,1440]) {
    const root = element(theme, [], null, lang), nested = element(opposite(theme), [], root);
    const hosts = [root, element(undefined, [], root), element(undefined, ['hx-sys'], root), ...['pg-shell', 'pg-boot-frame', 'pg-mobile-drawer'].map(name => element(undefined, [name], root)), nested, element(undefined, ['hx-sys'], nested)];
    for (const [index, host] of hosts.entries()) {
      const env = resolve(host, width);
      facts.push([theme, lang, width, index, legacy.map(name => [name, env[name]])]);
    }
  }
  // Recorded from main's original tokens and unchanged Arabic adapter using
  // this bounded model, not from the proposal. Emitted CSS still needs proof.
  assert.equal(legacy.length, 185);
  assert.equal(facts.length, 128);
  assert.equal(createHash('sha256').update(JSON.stringify(facts)).digest('hex'), 'b595d38a7972772cba207335c6e16afc600b236711c90212e6a37e425b075549');
});

test('local bilingual fonts and opt-in type keep Arabic, identifiers and digits readable', () => {
  for (const file of ['lexend-deca.ttf', 'noto-sans-arabic.ttf', 'lexend-deca-OFL.txt', 'noto-sans-arabic-OFL.txt']) assert.ok(existsSync(new URL(`../app/fonts/${file}`, import.meta.url)));
  const arabic = entries.filter(entry => entry.context.at(-1) === '[lang="ar"]');
  const env = environment([...rootEntries, ...arabic]);
  assert.equal(expand(env['--bt-font-body'], env), 'var(--font-lexend-deca), var(--font-arabic)');
  const type = read('web/styles/typography.css');
  assert.match(type, /overflow-wrap: anywhere/);
  assert.match(type, /text-align: start/);
  assert.match(type, /font-variant-numeric: tabular-nums/);
  assert.match(type, /font-family: var\(--bt-font-numeric\)/);
  assert.match(type, /direction: ltr/);
  assert.match(type, /unicode-bidi: isolate/);
  assert.ok(!/overflow:\s*hidden|white-space:\s*nowrap|block-size:/.test(type));
  const layout = read('web/app/layout.tsx');
  assert.match(layout, /lang=\{locale\} dir=\{direction\(locale\)\} data-theme=\{theme\}/);
  assert.match(layout, /cookies\(\)/);
  assert.match(layout, /next\/font\/local/);
  assert.ok(!/fonts\.googleapis|next\/font\/google/.test(layout));
});

test('the token/type foundation is rule-clean and enters through the one stylesheet', () => {
  assert.deepEqual(inspectSource('web/styles/tokens.css', tokens), {});
  assert.deepEqual(inspectSource('web/styles/typography.css', read('web/styles/typography.css')), {});
  const globals = read('web/app/globals.css');
  assert.ok(globals.indexOf('styles/tokens.css') < globals.indexOf('styles/typography.css'));
  assert.equal((globals.match(/styles\/typography\.css/g) ?? []).length, 1);
});
