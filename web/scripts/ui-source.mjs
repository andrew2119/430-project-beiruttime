import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';
import nextVitals from 'eslint-config-next/core-web-vitals';
import { metadataIssues, motionTokenMs, propertyName, unwrap } from './ui-syntax.mjs';

// Use the parser and semantic plugin already owned by the pinned framework.
const framework = createRequire(import.meta.resolve('next'));
const cssParser = framework('postcss');
export const SEMANTIC_PLUGIN = nextVitals.find(entry => entry.plugins?.['jsx-a11y'])?.plugins['jsx-a11y'];
if (!SEMANTIC_PLUGIN) throw new Error('The pinned Next lint configuration must provide its jsx-a11y plugin instance.');
export const SEMANTIC_RULES = SEMANTIC_PLUGIN.configs.recommended.rules;
export const INTERFACE_CHECKS = Object.freeze({
  'bt-force-priority': 'BT-UI-61', 'bt-stack-escape': 'BT-UI-62', 'bt-palette-inline': 'BT-UI-63',
  'bt-runtime-weight': 'BT-UI-64', 'bt-slow-start': 'BT-UI-15', 'bt-time-budget': 'BT-UI-16',
  'bt-motion-literal': 'BT-UI-18', 'bt-timing-detour': 'BT-UI-18', 'bt-loop-detour': 'BT-UI-18',
  'bt-property-sweep': 'BT-UI-19', 'bt-vanishing-scale': 'BT-UI-20', 'bt-reflow-motion': 'BT-UI-21',
  'bt-touch-hover': 'BT-UI-40', 'bt-motion-owner': 'BT-UI-14', 'bt-fold-detour': 'BT-UI-13',
  'bt-viewport-unit': 'BT-UI-43', 'bt-boundary-quiet': 'BT-UI-49', 'bt-state-alert-gap': 'BT-UI-49',
  'bt-focus-lost': 'BT-UI-50', 'bt-title-absent': 'BT-UI-51', 'jsx-a11y': 'BT-UI-52',
  'bt-title-format': 'BT-UI-54', 'bt-modal-detour': 'BT-UI-55', 'bt-choice-detour': 'BT-UI-56',
  'bt-control-detour': 'BT-UI-57', 'bt-style-opaque': 'BT-UI-63', 'bt-motion-legacy': 'BT-UI-14',
});
export const TOKEN_OWNER = 'web/styles/tokens.css';
export const MOTION_OWNER = 'web/styles/bt-motion.css';
export const LEGACY_MOTION_OWNER = 'web/styles/motion.css';
export const LEGACY_MOTION_HASH = '020d59936efcd46cfc0c76ccc41cb64684f94721e7ba9065035e6c789614ae43';
const legacyMotionClasses = new Set(['pg-boot-shimmer', 'pg-card', 'pg-chonk', 'pg-dept-card', 'pg-dept-card-go', 'pg-dept-link', 'pg-detail-arrive', 'pg-iconbtn', 'pg-list-grid', 'pg-list-item', 'pg-modal', 'pg-nav-icon', 'pg-nav-icon-glyph', 'pg-nav-item', 'pg-overlay', 'pg-popover', 'pg-row', 'pg-seg-thumb', 'pg-skeleton', 'pg-skeleton-copy', 'pg-skeleton-row-composed', 'ui-image-frame-glyph', 'ui-image-frame-img', 'ui-image-frame-placeholder']);
const legacyMotionFrames = new Set([
  'pg-slideUpAndFade', 'pg-fadeOut', 'pg-overlayIn', 'pg-overlayOut', 'pg-modalIn', 'pg-modalOut',
  'pg-listIn', 'pg-contentIn', 'pg-listOut', 'pg-shimmer', 'pg-skeleton-pulse', 'share-fade-up',
  'bt-drawer-in-rtl', 'bt-drawer-out-rtl', 'pg-face-in', 'proto-set-flash',
  'pg-icon-wave', 'pg-icon-announce', 'pg-icon-shuffle', 'pg-icon-spin', 'pg-icon-open', 'pg-icon-drop',
  'pg-icon-rev', 'pg-icon-stamp', 'pg-icon-bounce', 'pg-icon-settle', 'pg-icon-pulse', 'pg-icon-breathe',
  'psb-drawer-in', 'psb-drawer-out', 'psb-scrim-in', 'psb-scrim-out',
  'sx-progress', 'sx-slide', 'sx-clip', 'sx-fade', 'sx-tb-slide', 'sx-tb-edge',
]);
// Validation-only compatibility facts, not another runtime pacing table.
const legacyPacing = Object.freeze({
  '--ease-standard': 'cubic-bezier(0.4,0,0.2,1)', '--ease-out-soft': 'cubic-bezier(0,0,0.2,1)',
  '--ease-in-hard': 'cubic-bezier(0.4,0,1,1)', '--ease-overshoot': 'cubic-bezier(0.175,0.885,0.32,1.1)',
  '--ease-settle': 'cubic-bezier(0.17,0.03,0.04,1.02)', '--ease-expressive': 'cubic-bezier(0.31,0.1,0.08,0.96)',
  '--ds-motion-fast': '0.15s', '--ds-motion-popover': '0.2s', '--ds-motion-overlay': '0.3s',
  '--ds-motion-theme': '0.45s', '--ds-motion-reduced': '0.001ms', '--ds-motion-nav-pending': '0.12s',
  '--ds-motion-loader-safety': '5s', '--ds-motion-expressive': '0.6s', '--ds-motion-press': '0.13s',
  '--ds-motion-shimmer': '1.6s', '--ds-motion-image-reveal': '0.18s',
  '--motion-fast': 'var(--ds-motion-fast)', '--motion-overlay': 'var(--ds-motion-overlay)', '--ease': 'var(--ease-standard)',
});
export const LONG_TIMES = Object.freeze({
  '--bt-motion-theme': 'Occasional whole-document theme crossfade.',
  '--bt-motion-icon': 'Occasional single-play navigation icon arc.',
  '--bt-motion-pulse': 'Loading placeholder period, not interaction delay.',
  '--bt-motion-safety': 'Safety deadline, not visible motion.',
  '--ds-motion-theme': 'Compatibility document crossfade.',
  '--ds-motion-expressive': 'Compatibility single-play icon arc.',
  '--ds-motion-shimmer': 'Compatibility loading placeholder period.',
  '--ds-motion-loader-safety': 'Compatibility safety deadline.',
});
export const LAYER_SLOTS = Object.freeze([
  '--bt-layer-content', '--bt-layer-pinned', '--bt-layer-navigation', '--bt-layer-shade',
  '--bt-layer-window', '--bt-layer-menu', '--bt-layer-toast', '--bt-layer-loading', '--bt-layer-skip',
  '--z-skip-link', '--z-loading-overlay', '--z-avatar',
]);
// Trust only these implementations for screen-covering layers or local choice paint.
const surfaceOwners = new Set(['web/styles/ui.css', 'packages/ui/src/dialog.tsx', 'packages/ui/src/sheet.tsx']);
const choiceOwners = new Set(['packages/ui/src/segmented.tsx', 'packages/ui/src/segmented-thumb.tsx']);
const numberText = '[+-]?(?:\\d*\\.\\d+|\\d+\\.?\\d*)(?:e[+-]?\\d+)?';
const reflowProperty = /^(?:(?:min-|max-)?(?:width|height|inline-size|block-size)|top|left|right|bottom|inset(?:-[\w-]+)?|margin(?:-[\w-]+)?|padding(?:-[\w-]+)?|font-(?:size|weight|stretch)|border-(?:(?:(?:top|right|bottom|left|inline|block)(?:-(?:start|end))?-)?width|spacing)|(?:row-|column-)?gap|grid-(?:template|auto)-(?:rows|columns)|grid-(?:row|column)(?:-(?:start|end))?|flex-(?:basis|grow|shrink)|line-height|letter-spacing|word-spacing|text-indent|vertical-align|column-(?:count|width)|aspect-ratio)$/;
const paletteClass = /^(?:bg|text|border|ring|fill|stroke|from|via|to)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(?:-\d{2,3})?(?:\/\d+)?$/;
const colourNames = new Set(('aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen').split(' '));

export function cssDeclarations(source) {
  const result = [];
  const tree = cssParser.parse(source);
  tree.walkDecls(node => {
    const context = [];
    for (let parent = node.parent; parent?.parent; parent = parent.parent) context.unshift(parent.type === 'atrule' ? `@${parent.name} ${parent.params}`.trim() : parent.selector);
    result.push({ prop: node.prop.startsWith('--') ? node.prop : node.prop.toLowerCase(), value: node.value, context, offset: node.source?.start?.offset ?? 0 });
  });
  return result;
}
export function declaredLayers(source) {
  return new Set(cssDeclarations(source).filter(({ prop }) => LAYER_SLOTS.includes(prop)).map(({ prop }) => prop));
}
// Variable names are not colours or times. Literal fallbacks still are consumer values.
function withoutVariables(value) {
  let out = '';
  for (let at = 0; at < value.length;) {
    if (/^var\(/i.test(value.slice(at))) {
      let depth = 1; at += 4;
      const start = at;
      while (at < value.length && depth) { if (value[at] === '(') depth++; if (value[at] === ')') depth--; at++; }
      const fallback = commaParts(value.slice(start, at - 1)).slice(1).join(',');
      out += fallback ? withoutVariables(fallback) : ' ';
    } else out += value[at++];
  }
  return out;
}
function commaParts(value) {
  const result = []; let depth = 0, start = 0;
  for (let i = 0; i < value.length; i++) {
    if (value[i] === '(') depth++;
    if (value[i] === ')') depth--;
    if (value[i] === ',' && depth === 0) { result.push(value.slice(start, i)); start = i + 1; }
  }
  result.push(value.slice(start)); return result;
}
const kebab = name => name.replace(/[A-Z]/g, char => `-${char.toLowerCase()}`);
const isZero = text => new RegExp(`^${numberText}(?:px|%)?$`, 'i').test(text) && Number(text.replace(/px|%/gi, '')) === 0;
const isLayer = prop => /^(?:--bt-layer-|--z-)/.test(prop);
const isMotion = prop => /^(?:transition|animation)(?:-[\w-]+)?$/.test(prop);
const isGuardedStyle = prop => /^(?:color|background|fill|stroke|border|outline|box-shadow|text-shadow|z-index|transform|translate|rotate|scale|height|block-size|position|inset|grid-template-rows)/.test(prop) || isMotion(prop) || prop.startsWith('--');
const cleanValue = value => value.replace(/\/\*[\s\S]*?\*\//g, ' ');
function outlineReset(prop, value) {
  const words = cleanValue(value).trim().toLowerCase().split(/\s+/);
  const zero = word => new RegExp(`^${numberText}(?:[a-z]+|%)?$`, 'i').test(word) && parseFloat(word) === 0;
  if (prop === 'outline-style') return words.includes('none');
  if (prop === 'outline-width') return words.some(zero);
  return prop === 'outline' && words.some(word => word === 'none' || zero(word));
}
function componentWords(value) {
  const words = []; let depth = 0, start = 0;
  for (let at = 0; at <= value.length; at++) {
    if (value[at] === '(') depth++;
    if (value[at] === ')') depth--;
    if (at === value.length || (depth === 0 && /\s/.test(value[at]))) {
      if (at > start) words.push(value.slice(start, at));
      start = at + 1;
    }
  }
  return words;
}
function transitionProperties(value) {
  // Time, curve and behavior components do not name a property. An empty result
  // in a shorthand therefore leaves the browser's default `all` in effect.
  return componentWords(value.toLowerCase()).filter(word =>
    !new RegExp(`^${numberText}(?:ms|s)$`, 'i').test(word) &&
    !/^(?:var|calc|min|max|clamp|cubic-bezier|steps|linear)\(/.test(word) &&
    !/^(?:ease(?:-in-out|-in|-out)?|linear|step-start|step-end|allow-discrete|normal)$/.test(word));
}
function literalColourFunctions(value) {
  let count = 0;
  for (const match of value.matchAll(/\b(?:rgba?|hsla?|hwb|color|oklch|oklab|lab|lch|device-cmyk)\s*\(/gi)) {
    let depth = 1, at = match.index + match[0].length, start = at;
    while (at < value.length && depth) { if (value[at] === '(') depth++; if (value[at] === ')') depth--; at++; }
    const args = value.slice(start, at - 1);
    // A relative colour starts from its token, not from an inline palette seed.
    if (/^\s*from\s+var\(/i.test(args)) continue;
    const plain = withoutVariables(args);
    if (new RegExp(`(?<![\\w-])${numberText}|\\bnone\\b`, 'i').test(plain)) count++;
  }
  return count;
}

/** Local constant/conditional/template evaluation. Unknown styling is review debt,
 * not an invitation to ignore the readable literal pieces of that expression. */
function evaluator(tree) {
  const constants = new Map(), scopes = new Map();
  const gather = node => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      let scope = node.parent;
      while (scope && !ts.isBlock(scope) && !ts.isSourceFile(scope)) scope = scope.parent;
      if (!scopes.has(scope)) scopes.set(scope, new Map());
      const immutable = Boolean(node.parent.flags & ts.NodeFlags.Const);
      scopes.get(scope).set(node.name.text, { value: node.initializer, immutable });
      if (ts.isSourceFile(scope) && immutable) constants.set(node.name.text, node.initializer);
    }
    if ((ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) && node.name) {
      let scope = node.parent;
      while (scope && !ts.isBlock(scope) && !ts.isSourceFile(scope)) scope = scope.parent;
      if (!scopes.has(scope)) scopes.set(scope, new Map());
      scopes.get(scope).set(node.name.text, { value: node, immutable: false });
    }
    ts.forEachChild(node, gather);
  };
  gather(tree);
  const lookup = node => {
    const name = node.text;
    for (let scope = node.parent; scope; scope = scope.parent) {
      if (scopes.get(scope)?.has(name)) return scopes.get(scope).get(name);
      if (ts.isFunctionLike(scope) && scope.parameters.some(parameter => parameter.name.getText(tree).split(/\W+/).includes(name))) return { immutable: false };
    }
    return undefined;
  };
  const binding = node => { const found = lookup(node); return found?.immutable ? found.value : undefined; };
  const shadowed = node => Boolean(lookup(node));
  function values(raw, seen = new Set(), env = {}) {
    const node = unwrap(raw);
    if (!node) return { words: [''], opaque: false };
    if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)) return { words: [node.text], opaque: false };
    if (node.kind === ts.SyntaxKind.TrueKeyword) return { words: ['true'], opaque: false };
    if (node.kind === ts.SyntaxKind.NullKeyword || node.kind === ts.SyntaxKind.FalseKeyword) return { words: [''], opaque: false };
    if (ts.isIdentifier(node)) {
      if (node.text in env) return { words: [String(env[node.text] ?? '')], opaque: false };
      if (node.text === 'undefined') return { words: [''], opaque: false };
      const local = binding(node);
      if (local && !seen.has(node.text)) return values(local, new Set([...seen, node.text]), env);
      return { words: [''], opaque: true };
    }
    if (ts.isConditionalExpression(node)) {
      const condition = truth(node.condition, env);
      if (condition !== null) return values(condition ? node.whenTrue : node.whenFalse, seen, env);
      const yes = values(node.whenTrue, seen, env), no = values(node.whenFalse, seen, env);
      return { words: [...yes.words, ...no.words], opaque: yes.opaque || no.opaque };
    }
    if (ts.isTemplateExpression(node)) {
      let words = [node.head.text], opaque = false;
      for (const part of node.templateSpans) {
        const next = values(part.expression, seen, env);
        words = words.flatMap(prefix => next.words.map(value => prefix + value + part.literal.text)).slice(0, 64);
        opaque ||= next.opaque;
      }
      return { words, opaque };
    }
    if (ts.isBinaryExpression(node)) {
      if (node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
        const left = values(node.left, seen, env), right = values(node.right, seen, env);
        return { words: left.words.flatMap(a => right.words.map(b => a + b)).slice(0, 64), opaque: left.opaque || right.opaque };
      }
      if (node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
        const right = values(node.right, seen, env); return { words: ['', ...right.words], opaque: right.opaque };
      }
      if ([ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)) {
        const a = values(node.left, seen, env), b = values(node.right, seen, env); return { words: [...a.words, ...b.words], opaque: a.opaque || b.opaque };
      }
    }
    if (ts.isCallExpression(node) && /^(?:readMotionToken|readEasingToken)$/.test(node.expression.getText(tree))) {
      const token = values(node.arguments[0], seen, env);
      return { words: token.words.map(name => `var(${name})`), opaque: token.opaque };
    }
    if (ts.isCallExpression(node) && /^(?:cn|clsx|classNames)$/.test(node.expression.getText(tree))) {
      let words = [''], opaque = false;
      for (const arg of node.arguments) {
        let result;
        if (ts.isObjectLiteralExpression(arg)) {
          result = { words: [''], opaque: false };
          for (const entry of arg.properties) {
            const key = propertyName(entry.name);
            if (key) result.words = result.words.flatMap(value => [value, `${value} ${key}`]);
            else result.opaque = true;
          }
        } else result = values(arg, seen, env);
        words = words.flatMap(a => result.words.map(b => `${a} ${b}`)).slice(0, 64); opaque ||= result.opaque;
      }
      return { words, opaque };
    }
    return { words: [''], opaque: true };
  }
  function truth(raw, env = {}) {
    const node = unwrap(raw);
    if (node?.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node?.kind === ts.SyntaxKind.FalseKeyword) return false;
    if (node && ts.isBinaryExpression(node) && [ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken].includes(node.operatorToken.kind)) {
      const a = values(node.left, new Set(), env), b = values(node.right, new Set(), env);
      if (!a.opaque && !b.opaque && a.words.length === 1 && b.words.length === 1) return /!/.test(node.operatorToken.getText(tree)) ? a.words[0] !== b.words[0] : a.words[0] === b.words[0];
    }
    return null;
  }
  return { values, truth, constants, binding, shadowed };
}
function returnPaths(fn) {
  if (!fn?.body) return [undefined];
  if (!ts.isBlock(fn.body)) return [fn.body];
  const paths = [];
  const walk = node => {
    if (ts.isReturnStatement(node)) { paths.push(node.expression); return; }
    if (!ts.isFunctionLike(node)) ts.forEachChild(node, walk);
  };
  ts.forEachChild(fn.body, walk);
  const returns = node => {
    if (ts.isReturnStatement(node) || ts.isThrowStatement(node)) return true;
    if (ts.isBlock(node)) return Boolean(node.statements.length && returns(node.statements.at(-1)));
    if (ts.isIfStatement(node)) return Boolean(node.elseStatement && returns(node.thenStatement) && returns(node.elseStatement));
    return false;
  };
  if (!returns(fn.body)) paths.push(undefined);
  return paths;
}
function defaultFunction(tree, constants) {
  for (const statement of tree.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.DefaultKeyword)) return statement;
    if (ts.isExportAssignment(statement)) {
      let node = unwrap(statement.expression);
      if (node && ts.isIdentifier(node)) node = constants.get(node.text) ?? tree.statements.find(part => ts.isFunctionDeclaration(part) && part.name?.text === node.text);
      return node;
    }
  }
}

export function inspectSource(file, source, { layers = new Set(), legacyMotionAllowed = false } = {}) {
  const issues = {};
  const add = (name, amount = 1) => { if (amount) issues[name] = (issues[name] ?? 0) + amount; };
  const count = (name, value, pattern) => add(name, [...value.matchAll(pattern)].length);
  const tokens = file === TOKEN_OWNER, motion = file === MOTION_OWNER;
  const frozenMotion = file === LEGACY_MOTION_OWNER && createHash('sha256').update(source).digest('hex') === LEGACY_MOTION_HASH;
  const legacyAllowed = legacyMotionAllowed || frozenMotion;
  if (file === LEGACY_MOTION_OWNER && !frozenMotion) add('bt-motion-legacy');
  const declaration = (prop, value, context = [], keyframe = false, sharedFold = false) => {
    value = cleanValue(value);
    const plain = withoutVariables(value);
    const kept = ['--bt-motion-kept-animation', '--bt-motion-kept-transition', '--bt-motion-kept-iterations'].includes(prop);
    if (/^--(?:(?:bt|ds)-motion-|bt-ease-|ease(?:-|$)|motion(?:-|$))/.test(prop) && !kept) {
      const legacyContext = prop.startsWith('--ease-') ? '@theme' : ':root';
      const exactLegacy = tokens && context.join('\n') === legacyContext && legacyPacing[prop] === value.replace(/\s+/g, '');
      if (!(motion && prop.startsWith('--bt-')) && !exactLegacy) add('bt-motion-owner');
    }
    const colourText = plain.replace(/\burl\([^)]*\)|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/gi, ''), lower = colourText.toLowerCase();
    if (!tokens) {
      count('bt-palette-inline', colourText, /#[\da-f]{3,8}\b/gi);
      add('bt-palette-inline', literalColourFunctions(value.replace(/\burl\([^)]*\)|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/gi, '')));
      if (/^(?:--|color|background|border|outline|fill|stroke|box-shadow|text-shadow)/.test(prop)) {
        for (const word of lower.match(/[a-z]+/g) ?? []) if (colourNames.has(word)) add('bt-palette-inline');
      }
      if (isMotion(prop) || prop.startsWith('--')) {
        // Owning literal pacing does not permit a prohibited response curve.
        if (!(motion && /^--bt-(?:motion|ease)-/.test(prop))) {
          count('bt-motion-literal', plain, new RegExp(`(?<![\\w.-])${numberText}(?:ms|s)\\b`, 'gi'));
          count('bt-motion-literal', plain, /\b(?:cubic-bezier|steps|linear)\(|(?<![\w-])(?:ease(?:-in-out|-in|-out)?|linear|step-start|step-end)(?![\w-])/gi);
        }
        count('bt-slow-start', plain, /(?<![\w-])ease-in(?![\w-])/gi);
        if (/var\(\s*--ease-in-hard\s*\)/.test(value)) add('bt-slow-start');
      }
    }
    if (!legacyAllowed && (isMotion(prop) || prop.startsWith('--'))) for (const name of value.match(/[\w-]+/g) ?? []) if (legacyMotionFrames.has(name)) add('bt-motion-legacy');
    if (/^transition(?:-property)?$/.test(prop)) for (const part of commaParts(value)) {
      const words = transitionProperties(part);
      if (words.includes('all') || (prop === 'transition' && !words.length)) add('bt-property-sweep');
      if (prop === 'transition-property' && !words.length) add('bt-style-opaque');
      for (const name of words) if (reflowProperty.test(name) && !(sharedFold && name === 'grid-template-rows')) add('bt-reflow-motion');
    }
    if (keyframe && reflowProperty.test(prop)) add('bt-reflow-motion');
    if (prop === 'grid-template-rows' && /\b0fr\b/i.test(value) && !sharedFold) add('bt-fold-detour');
    if (/\b100vh\b/i.test(plain)) add('bt-viewport-unit');
    if (isLayer(prop) && (file !== TOKEN_OWNER || !LAYER_SLOTS.includes(prop))) add('bt-stack-escape');
    if (prop === 'z-index') {
      const match = /^var\(\s*(--[\w-]+)\s*\)$/.exec(value.trim());
      if (!match || !layers.has(match[1]) || !LAYER_SLOTS.includes(match[1])) add('bt-stack-escape');
    }
    if (prop === 'transform') for (const match of value.matchAll(/\bscale(?:3d|x|y|z)?\(([^)]+)\)/gi)) if (match[1].split(/[,\s]+/).some(isZero)) add('bt-vanishing-scale');
    if (prop === 'scale' && value.split(/\s+/).some(isZero)) add('bt-vanishing-scale');
    const capability = pattern => context.some(part => /^@media\b/i.test(part) && part.slice(6).split(',').every(query => pattern.test(query) && !/\b(?:not|or)\b/i.test(query)));
    if (context.some(part => /:hover\b/i.test(part)) && /^(?:transform|translate|scale|rotate|animation(?:-[\w-]+)?)$/.test(prop) && !(capability(/\(\s*hover\s*:\s*hover\s*\)/i) && capability(/\(\s*pointer\s*:\s*fine\s*\)/i))) add('bt-touch-hover');
  };
  const fullScreen = entries => {
    if (surfaceOwners.has(file)) return;
    const fixed = entries.some(entry => entry.prop === 'position' && entry.value.trim().toLowerCase() === 'fixed');
    const shorthand = entries.some(entry => entry.prop === 'inset' && entry.value.trim().split(/\s+/).every(isZero));
    const edges = ['top', 'right', 'bottom', 'left'].every(prop => entries.some(entry => entry.prop === prop && isZero(entry.value.trim())));
    if (fixed && (shorthand || edges)) add('bt-modal-detour');
  };
  function stylesheet(text) {
    count('bt-force-priority', text, /!\s*important\b/gi);
    let tree;
    try { tree = cssParser.parse(text); } catch { add('bt-style-opaque'); return; }
    const entries = cssDeclarations(text), timeTokens = {};
    for (const { prop, value } of entries) if (prop.startsWith('--') && !(prop in timeTokens)) timeTokens[prop] = value;
    tree.walkRules(node => {
      if (!legacyAllowed) for (const [, name] of node.selector.matchAll(/\.([\w-]+)/g)) if (legacyMotionClasses.has(name)) add('bt-motion-legacy');
    });
    tree.walkAtRules(node => {
      if (/^(?:-webkit-)?keyframes$/i.test(node.name)) {
        if (!motion && !frozenMotion) add('bt-motion-owner');
        if (!legacyAllowed && legacyMotionFrames.has(node.params.trim())) add('bt-motion-legacy');
      }
      if (node.name.toLowerCase() === 'apply') classes(node.params);
      if (/fonts\.googleapis|material-symbols/i.test(node.params)) add('bt-runtime-weight');
    });
    const foldBase = '@layer components\n:where(:where(.bt-fold))';
    const foldOpen = '@layer components\n:where(:where(.bt-fold)[data-state="open"])';
    const foldPair = motion && [[foldBase, '0fr'], [foldOpen, '1fr']].every(([context, value]) => {
      const rows = entries.filter(entry => entry.prop === 'grid-template-rows' && entry.context.join('\n') === context);
      return rows.length === 1 && cleanValue(rows[0].value).trim() === value;
    });
    for (const entry of entries) {
      const context = entry.context.join('\n');
      const sharedFold = foldPair && (
        (entry.prop === 'grid-template-rows' && [foldBase, foldOpen].includes(context)) ||
        (context === foldBase && entry.prop === 'transition' && cleanValue(entry.value).trim().replace(/\s+/g, ' ') === 'grid-template-rows var(--bt-motion-menu) var(--bt-ease-out)')
      );
      declaration(entry.prop, entry.value, entry.context, entry.context.some(part => /^@(?:-webkit-)?keyframes\b/i.test(part)), sharedFold);
      if ((tokens || motion) && /^--(?:bt|ds)-motion-/.test(entry.prop) && entry.prop !== '--bt-motion-kept-iterations') {
        const time = motionTokenMs(entry.value, timeTokens, new Set([entry.prop]));
        if (time === null || (time > 300 && !(entry.prop in LONG_TIMES))) add('bt-time-budget');
      }
    }
    const groups = new Map();
    for (const entry of entries) { const key = entry.context.join('\n'); groups.set(key, [...(groups.get(key) ?? []), entry]); }
    const focusTreatment = group => {
      const final = new Map(group.map(entry => [entry.prop, cleanValue(entry.value)]));
      const outline = final.get('outline') ?? '';
      const restored = /(?:\d*\.)?[1-9]\d*(?:px|rem|em)/.test(outline) && /\b(?:solid|dashed|dotted|double|groove|ridge|inset|outset|auto)\b/i.test(outline) && !outlineReset('outline', outline) && !['outline-width', 'outline-style'].some(prop => outlineReset(prop, final.get(prop) ?? ''));
      const ring = /(?:\d*\.)?[1-9]\d*(?:px|rem|em)/.test(final.get('box-shadow') ?? '') && final.get('box-shadow') !== 'none';
      return restored || ring;
    };
    for (const group of groups.values()) {
      fullScreen(group);
      if (!group.some(entry => outlineReset(entry.prop, entry.value)) || focusTreatment(group)) continue;
      // Certify only a simple, later same-context focus pair. Complex selectors,
      // wrappers and cross-file cascade relationships still need keyboard review.
      const { context } = group[0], selector = context.at(-1) ?? '';
      const paired = commaParts(selector).every(base => /^[.#][\w-]+$/.test(base.trim()) && [...groups.values()].some(candidate =>
        candidate[0].offset > group.at(-1).offset &&
        candidate[0].context.slice(0, -1).join('\n') === context.slice(0, -1).join('\n') &&
        [':focus-visible', ':focus'].some(state => candidate[0].context.at(-1)?.trim() === base.trim() + state) &&
        focusTreatment(candidate)));
      if (!paired) add('bt-focus-lost');
    }
  }
  function classes(text) {
    const list = text.split(/\s+/).filter(Boolean);
    for (const item of list) {
      const base = item.split(/:(?![^\[]*\])/).at(-1);
      if (!legacyAllowed && legacyMotionClasses.has(base)) add('bt-motion-legacy');
      if (paletteClass.test(base)) add('bt-palette-inline');
      const arbitrary = /^\[([\w-]+):([\s\S]*)\]$/.exec(base);
      if (arbitrary) declaration(arbitrary[1], arbitrary[2].replace(/_/g, ' '), /(?:^|:)hover:/.test(item) ? [':hover'] : []);
      const paint = /^(bg|text|border|ring|fill|stroke|from|via|to)-\[([\s\S]*)\]$/.exec(base);
      if (paint) declaration(paint[1] === 'bg' ? 'background' : 'color', paint[2].replace(/_/g, ' '));
      const transition = /^transition-\[([\s\S]*)\]$/.exec(base);
      if (transition) declaration('transition-property', transition[1].replace(/_/g, ' '));
      if (/^(?:min-|max-)?h-screen$/.test(base) || /^h-\[100vh\]$/i.test(base)) add('bt-viewport-unit');
      const scale = /^scale-\[([^\]]+)\]$/.exec(base);
      if (scale && isZero(scale[1])) add('bt-vanishing-scale');
      if (base === 'transition-all') add('bt-property-sweep');
      if (base === 'scale-0') add('bt-vanishing-scale');
      if (/^animate-(?:spin|pulse)$/.test(base)) add('bt-loop-detour');
      if (/^-?z-(?:\d|\[)/.test(base)) add('bt-stack-escape');
      if (/^(?:duration|delay)-\d+$|^ease-(?:in|out|in-out)$/.test(base)) add('bt-timing-detour');
      if (/(?:^|:)hover:/.test(item) && /^(?:-?translate|scale|rotate|skew|animate)-/.test(base)) add('bt-touch-hover');
      if (/^(?:duration|delay|ease|animate)-\[/.test(base)) {
        const inside = withoutVariables(base).replace(/_/g, ' ');
        count('bt-motion-literal', inside, new RegExp(`${numberText}(?:ms|s)\\b|\\b(?:cubic-bezier|steps)\\(|\\b(?:ease(?:-in-out|-in|-out)?|linear)\\b`, 'gi'));
      }
      if (!choiceOwners.has(file) && /(?:-toggle-item-active|^bt-segment-active$)/.test(base)) add('bt-choice-detour');
    }
    if (!surfaceOwners.has(file) && list.includes('fixed') && (list.includes('inset-0') || ['top-0', 'right-0', 'bottom-0', 'left-0'].every(part => list.includes(part)))) add('bt-modal-detour');
  }
  if (file.endsWith('.css')) { stylesheet(source); return issues; }
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, /\.[cm]?jsx?$/.test(file) ? ts.ScriptKind.JSX : /\.tsx$/.test(file) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const { values, truth, constants, binding, shadowed } = evaluator(tree);
  const sharedFaces = new Set();
  const scanSpecifier = specifier => {
    if (/^(?:chart\.js|three|gsap|next\/font\/google)(?:\/|$)|fonts\.googleapis|material-symbols/.test(specifier)) add('bt-runtime-weight');
    const target = specifier.startsWith('.') ? resolve('/', dirname(file), specifier) : '';
    const internal = /(?:^@beirut-time\/ui\/|(?:^|\/)alternate-ui(?:\/|$)|(?:^|\/)ui-private(?:\/|$))/.test(specifier) || target.startsWith('/packages/ui/src/');
    const publicBarrel = target === '/packages/ui/src/index' || target === '/packages/ui/src/index.tsx' || ['@beirut-time/ui/motion', '@beirut-time/ui/motion-easing'].includes(specifier);
    if (internal && !publicBarrel && !file.startsWith('packages/ui/src/')) add('bt-control-detour');
  };
  for (const node of tree.statements) if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
    scanSpecifier(node.moduleSpecifier.text);
    if (ts.isImportDeclaration(node) && ['@beirut-time/ui', '@/shell/primitives'].includes(node.moduleSpecifier.text) && node.importClause?.namedBindings && ts.isNamedImports(node.importClause.namedBindings)) for (const name of node.importClause.namedBindings.elements) if ((name.propertyName?.text ?? name.name.text) === 'State') sharedFaces.add(name.name.text);
  }
  const attrs = node => (ts.isJsxElement(node) ? node.openingElement : node).attributes?.properties ?? [];
  const attribute = (node, name) => attrs(node).find(attr => ts.isJsxAttribute(attr) && attr.name.getText(tree) === name);
  const attrValues = (node, name, env = {}) => {
    const init = attribute(node, name)?.initializer;
    return values(init && ts.isJsxExpression(init) ? init.expression : init, new Set(), env);
  };
  const actualFocus = text => {
    // Extra variants (disabled, hover, dark, etc.) cannot certify every keyboard
    // focus state. An unconditional focus/focus-visible width is required.
    const focused = text.split(/\s+/).filter(item => /^(?:focus-visible|focus):[^:]+$/.test(item)).map(item => item.split(':').at(-1));
    const width = item => {
      if (/^(?:ring|outline)$/.test(item)) return true;
      const match = /^(?:ring|outline)-(\d+|\[(?:\d*\.)?\d+(?:px|rem|em)\])$/.exec(item);
      return Boolean(match && Number(match[1].replace(/[\[\]a-z]/g, '')) > 0);
    };
    return focused.some(width) && !focused.some(item => /^(?:ring|outline)-(?:0|none)$/.test(item));
  };
  function numericExpression(raw, seen = new Set()) {
    const node = unwrap(raw);
    if (!node) return false;
    if (ts.isNumericLiteral(node)) return true;
    if (ts.isCallExpression(node) && node.expression.getText(tree) === 'Number' && node.arguments.length === 1) return true;
    if (ts.isPrefixUnaryExpression(node)) return numericExpression(node.operand, seen);
    if (ts.isBinaryExpression(node) && ['+', '-', '*', '/', '%', '**'].includes(node.operatorToken.getText(tree))) return numericExpression(node.left, seen) && numericExpression(node.right, seen);
    if (ts.isIdentifier(node)) {
      if (seen.has(node.text)) return false;
      const local = binding(node);
      if (local) return numericExpression(local, new Set([...seen, node.text]));
      for (let scope = node.parent; scope; scope = scope.parent) if (ts.isFunctionLike(scope)) {
        const parameter = scope.parameters.find(part => ts.isIdentifier(part.name) && part.name.text === node.text);
        if (parameter) return parameter.type?.kind === ts.SyntaxKind.NumberKeyword;
      }
    }
    return false;
  }
  function readableTranslation(raw, prop) {
    const node = unwrap(raw);
    if (!node || !ts.isTemplateExpression(node) || !['transform', 'translate'].includes(prop) || !node.templateSpans.every(part => numericExpression(part.expression))) return false;
    const sample = node.head.text + node.templateSpans.map(part => `1${part.literal.text}`).join('');
    const length = `${numberText}(?:px|rem|em|%)?`;
    return prop === 'translate' ? new RegExp(`^\\s*${length}(?:\\s+${length}){0,2}\\s*$`, 'i').test(sample) : new RegExp(`^(?:\\s*translate(?:[xyz]|3d)?\\(\\s*${length}(?:\\s*,\\s*${length}){0,2}\\s*\\)\\s*)+$`, 'i').test(sample);
  }
  function styleValue(prop, raw, frame = false) {
    const result = values(raw);
    if (result.opaque && (frame || isGuardedStyle(prop)) && !readableTranslation(raw, prop)) add('bt-style-opaque');
    for (const value of result.words) declaration(prop, value, [], frame);
    return result.words.map(value => ({prop, value}));
  }
  function styleObject(raw, frame = false) {
    let node = unwrap(raw);
    if (node && ts.isIdentifier(node)) {
      // Const does not freeze an object. Referenced containers may have been
      // mutated; inspecting an initializer cannot certify their current value.
      add('bt-style-opaque'); node = unwrap(binding(node));
    }
    if (node && ts.isConditionalExpression(node)) return [...styleObject(node.whenTrue, frame), ...styleObject(node.whenFalse, frame)];
    if (!node || !ts.isObjectLiteralExpression(node)) { add('bt-style-opaque'); return []; }
    const entries = [];
    for (const part of node.properties) {
      if (!ts.isPropertyAssignment(part) || !propertyName(part.name)) { add('bt-style-opaque'); continue; }
      let prop = part.name.text.startsWith('--') ? part.name.text : kebab(part.name.text);
      if (frame && ['offset', 'composite'].includes(prop)) continue;
      if (frame && prop === 'easing') prop = 'animation-timing-function';
      const value = unwrap(part.initializer);
      if (frame && ts.isArrayLiteralExpression(value)) for (const item of value.elements) entries.push(...styleValue(prop, item, true));
      else entries.push(...styleValue(prop, value, frame));
    }
    fullScreen(entries); return entries;
  }
  function keyframes(raw) {
    const node = unwrap(raw);
    if (node && ts.isArrayLiteralExpression(node)) { for (const frame of node.elements) styleObject(frame, true); }
    else styleObject(node, true);
  }
  function styleTarget(raw, seen = new Set()) {
    const node = unwrap(raw);
    if (!node) return false;
    if (ts.isPropertyAccessExpression(node)) return node.name.text === 'style';
    if (ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression)) return node.argumentExpression.text === 'style';
    if (ts.isIdentifier(node) && !seen.has(node.text) && binding(node)) return styleTarget(binding(node), new Set([...seen, node.text]));
    return false;
  }
  function cssWrite(prop, raw) {
    if (!prop.startsWith('--')) prop = prop.toLowerCase();
    if (prop === 'css-text') {
      const result = values(raw); if (result.opaque) add('bt-style-opaque');
      for (const text of result.words) stylesheet(`.bt-written-style { ${text} }`);
    } else styleValue(prop, raw);
  }
  function safeSpread(node, spread) {
    const object = unwrap(spread.expression);
    if (object && ts.isObjectLiteralExpression(object)) return object.properties.every(part => ts.isPropertyAssignment(part) && /^(?:id|title|lang|dir|type|name|value|disabled|aria-(?:label|labelledby|describedby)|data-[\w-]+)$/.test(propertyName(part.name) ?? ''));
    // The reviewed image delivery boundary forwards the native image rest props.
    // Callers still have their own spread/style review; no package-wide exemption.
    if (file !== 'packages/ui/src/image-frame.tsx' || node.tagName.getText(tree) !== 'img' || !object || !ts.isIdentifier(object) || object.text !== 'props') return false;
    for (let scope = node.parent; scope; scope = scope.parent) if (ts.isFunctionLike(scope)) return scope.parameters.some(parameter => ts.isObjectBindingPattern(parameter.name) && parameter.name.elements.some(part => part.dotDotDotToken && part.name.getText(tree) === 'props'));
    return false;
  }
  function rendered(raw, kind, env = {}, seen = new Set()) {
    const node = unwrap(raw);
    if (!node) return false;
    if (ts.isIdentifier(node) && binding(node) && !seen.has(node.text)) return rendered(binding(node), kind, env, new Set([...seen, node.text]));
    if (ts.isConditionalExpression(node)) {
      const decision = truth(node.condition, env);
      return decision !== null ? rendered(decision ? node.whenTrue : node.whenFalse, kind, env, seen) : rendered(node.whenTrue, kind, env, seen) && rendered(node.whenFalse, kind, env, seen);
    }
    if (ts.isJsxFragment(node)) return node.children.some(child => rendered(ts.isJsxExpression(child) ? child.expression : child, kind, env, seen));
    if (!ts.isJsxElement(node) && !ts.isJsxSelfClosingElement(node)) return false;
    const opening = ts.isJsxElement(node) ? node.openingElement : node;
    if (attrValues(opening, 'aria-hidden', env).words.includes('true') || attribute(opening, 'hidden')) return false;
    if (kind === 'state' && sharedFaces.has(opening.tagName.getText(tree))) {
      if (shadowed(opening.tagName)) { add('bt-style-opaque'); return false; }
      return attrValues(opening, 'kind', env).words.every(value => value === 'error');
    }
    if (kind === 'alert' && attrValues(opening, 'role', env).words.every(value => value === 'alert')) return true;
    return ts.isJsxElement(node) && node.children.some(child => rendered(ts.isJsxExpression(child) ? child.expression : child, kind, env, seen));
  }
  const visit = node => {
    if (!legacyAllowed) {
      const literals = ts.isStringLiteralLike(node) ? [node.text] : ts.isTemplateExpression(node) ? [node.head.text, ...node.templateSpans.map(part => part.literal.text)] : [];
      for (const text of literals) for (const name of text.match(/[\w-]+/g) ?? []) if (legacyMotionClasses.has(name) || legacyMotionFrames.has(name)) add('bt-motion-legacy');
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
      const target = unwrap(node.left);
      if (ts.isPropertyAccessExpression(target) && styleTarget(target.expression)) cssWrite(kebab(target.name.text), node.right);
      if (ts.isElementAccessExpression(target) && styleTarget(target.expression)) {
        const names = values(target.argumentExpression);
        if (names.opaque) add('bt-style-opaque');
        for (const name of names.words) cssWrite(kebab(name), node.right);
      }
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'setProperty' && styleTarget(node.expression.expression)) {
      const names = values(node.arguments[0]);
      if (names.opaque) add('bt-style-opaque');
      for (const name of names.words) cssWrite(name, node.arguments[1]);
      if (node.arguments[2]) {
        const priority = values(node.arguments[2]);
        if (priority.opaque) add('bt-style-opaque');
        if (priority.words.some(word => word.toLowerCase() === 'important')) add('bt-force-priority');
      }
    }
    if (ts.isCallExpression(node) && node.expression.getText(tree) === 'Object.assign' && styleTarget(node.arguments[0])) {
      for (const source of node.arguments.slice(1)) styleObject(source);
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'animate') {
      keyframes(node.arguments[0]);
      const options = unwrap(node.arguments[1]);
      if (!options || !ts.isObjectLiteralExpression(options)) add('bt-style-opaque');
      else for (const part of options.properties) {
        if (!ts.isPropertyAssignment(part) || !propertyName(part.name)) { add('bt-style-opaque'); continue; }
        const name = propertyName(part.name), result = values(part.initializer);
        if (['duration', 'delay', 'easing'].includes(name)) {
          if (result.opaque) add('bt-style-opaque');
          for (const value of result.words) declaration(name === 'easing' ? 'animation-timing-function' : `animation-${name}`, /^\d/.test(value) && !/[a-z]/i.test(value) ? `${value}ms` : value);
        }
      }
    }
    if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(tree) === 'require')) {
      const specifier = values(node.arguments[0]); if (specifier.opaque) add('bt-style-opaque'); else for (const text of specifier.words) scanSpecifier(text);
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      for (const spread of attrs(node).filter(ts.isJsxSpreadAttribute)) if (!safeSpread(node, spread)) add('bt-style-opaque');
      const classAttr = attribute(node, 'className');
      if (classAttr) {
        const result = attrValues(node, 'className');
        // Shared controls may forward their public className unchanged; unknown page styling may not certify itself.
        const rawClass = classAttr.initializer && ts.isJsxExpression(classAttr.initializer) ? unwrap(classAttr.initializer.expression) : undefined;
        const isForwardedName = part => ts.isIdentifier(part) && part.text === 'className';
        const forwarding = file.startsWith('packages/ui/src/') && rawClass && (isForwardedName(rawClass) || (ts.isCallExpression(rawClass) && /^(?:cn|clsx|classNames)$/.test(rawClass.expression.getText(tree)) && rawClass.arguments.some(isForwardedName) && rawClass.arguments.every(part => isForwardedName(part) || !values(part).opaque)));
        if (result.opaque && !forwarding) add('bt-style-opaque');
        for (const text of result.words) {
          classes(text);
          if (/(?:^|[\s:])outline-(?:none|0)(?:\s|$)/.test(text) && !actualFocus(text)) add('bt-focus-lost');
        }
      }
      if (!choiceOwners.has(file) && node.tagName.getText(tree) === 'button' && ['aria-pressed', 'aria-selected', 'aria-checked'].some(name => /===|==/.test(attribute(node, name)?.getText(tree) ?? '')) && attribute(node, 'onClick') && attrValues(node, 'className').words.some(value => /(?:^|\s)(?:bg-|[\w-]*(?:active|selected))/.test(value))) add('bt-choice-detour');
      for (const name of ['color', 'fill', 'stroke', 'transform']) if (attribute(node, name)) {
        const result = attrValues(node, name);
        if (result.opaque) add('bt-style-opaque');
        for (const value of result.words) declaration(name, value);
      }
      const style = attribute(node, 'style');
      if (style?.initializer && ts.isJsxExpression(style.initializer)) {
        const entries = styleObject(style.initializer.expression);
        if (entries.some(entry => outlineReset(entry.prop, entry.value)) && !attrValues(node, 'className').words.every(text => actualFocus(text) && /(?:^|\s)(?:focus-visible|focus):ring(?:-|\s|$)/.test(text))) add('bt-focus-lost');
      }
    }
    if (ts.isJsxElement(node)) {
      const opening = node.openingElement;
      if (opening.tagName.getText(tree).toLowerCase() === 'style') for (const child of node.children) {
        if (ts.isJsxExpression(child)) { const result = values(child.expression); if (result.opaque) add('bt-style-opaque'); for (const text of result.words) stylesheet(text); }
        if (ts.isJsxText(child) && child.text.trim()) stylesheet(child.text);
      }
      // A local choice group owning native pressed/checked buttons and selected paint is not the shared segmented control.
      const role = attrValues(opening, 'role').words;
      if (!choiceOwners.has(file) && role.some(value => ['group', 'radiogroup', 'tablist'].includes(value))) {
        let selected = false, painted = false;
        const childScan = child => {
          if (ts.isJsxOpeningElement(child) || ts.isJsxSelfClosingElement(child)) {
            if (['aria-pressed', 'aria-selected', 'aria-checked'].some(name => attribute(child, name))) selected = true;
            if (attribute(child, 'onClick') || attribute(child, 'onChange')) {
              const text = attrValues(child, 'className');
              if (text.words.some(value => /(?:^|\s)(?:bg-|[\w-]*(?:active|selected))/.test(value)) || attribute(child, 'style')) painted = true;
            }
          }
          ts.forEachChild(child, childScan);
        };
        node.children.forEach(childScan);
        if (selected && painted) add('bt-choice-detour');
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  const boundary = /^web\/app\/(?:.*\/)?error\.[jt]sx?$/.test(file), rootBoundary = /^web\/app\/global-error\.[jt]sx?$/.test(file);
  if (boundary || rootBoundary) {
    const paths = returnPaths(defaultFunction(tree, constants));
    if (!paths.length || paths.some(path => !rendered(path, rootBoundary ? 'alert' : 'state'))) add('bt-boundary-quiet');
  }
  if (file === 'packages/ui/src/index.tsx') {
    const state = tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'State');
    if (!state || returnPaths(state).some(path => !rendered(path, 'alert', { kind: 'error' }))) add('bt-state-alert-gap');
  }
  if (/^web\/app\/(?:.*\/)?(?:page|layout)\.[jt]sx?$/.test(file)) {
    const result = metadataIssues(tree, /\/layout\.[jt]sx?$/.test(file) || file.split('/').some(segment => segment.startsWith('@')));
    add('bt-title-absent', result.missing); add('bt-title-format', result.ending);
  }
  return issues;
}
