import ts from 'typescript';

/** Dimensional time arithmetic. Unknown variables, cycles and unsupported
 * expressions fail closed; do not execute a stylesheet expression as script. */
export function motionTokenMs(value, tokens = {}, seen = new Set()) {
  const expanded = value.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^()]+))?\)/g, (_, key, fallback) => {
    if (seen.has(key)) return '?';
    if (!(key in tokens)) return fallback ? `(${fallback})` : '?';
    const time = motionTokenMs(tokens[key], tokens, new Set([...seen, key]));
    return time === null ? '?' : `(${time}ms)`;
  });
  const parts = expanded.match(/calc\(|\d*\.?\d+(?:ms|s)?|[-+*/()]|\S/gi) ?? [];
  let at = 0;
  const fail = () => { throw new Error('Unsupported time expression'); };
  function atom() {
    const part = parts[at++];
    if (part === '(' || part === 'calc(') { const result = sum(); if (parts[at++] !== ')') fail(); return result; }
    if (part === '-') { const result = atom(); return { ...result, n: -result.n }; }
    const match = /^(\d*\.?\d+)(ms|s)?$/i.exec(part ?? '');
    if (!match) return fail();
    return { n: Number(match[1]) * (match[2]?.toLowerCase() === 's' ? 1000 : 1), time: Boolean(match[2]) };
  }
  function product() {
    let left = atom();
    while (parts[at] === '*' || parts[at] === '/') {
      const op = parts[at++], right = atom();
      if (op === '*' ? left.time && right.time : right.time || right.n === 0) fail();
      left = { n: op === '*' ? left.n * right.n : left.n / right.n, time: left.time || right.time };
    }
    return left;
  }
  function sum() {
    let left = product();
    while (parts[at] === '+' || parts[at] === '-') {
      const op = parts[at++], right = product();
      if (left.time !== right.time) fail();
      left = { n: op === '+' ? left.n + right.n : left.n - right.n, time: left.time };
    }
    return left;
  }
  try {
    const result = sum();
    return at === parts.length && Number.isFinite(result.n) && result.n >= 0 && (result.time || result.n === 0) ? result.n : null;
  } catch { return null; }
}

export const unwrap = node => {
  while (node && (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node))) node = node.expression;
  return node;
};
export const propertyName = node => node && (ts.isIdentifier(node) || ts.isStringLiteral(node)) ? node.text : undefined;
export const exported = node => node.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.ExportKeyword);

/** Conservatively inspect all metadata paths. An imported helper, a spread or
 * a re-export is opaque, not proof that a title is descriptive and standard. */
export function metadataIssues(tree, allowsMissing = false) {
  const constants = new Map(), exports = new Map(), declarations = new Map();
  const failures = { missing: 0, ending: 0 };
  for (const statement of tree.statements) {
    if (ts.isVariableStatement(statement)) for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name)) continue;
      declarations.set(declaration.name.text, declaration.initializer);
      if (statement.declarationList.flags & ts.NodeFlags.Const) constants.set(declaration.name.text, declaration.initializer);
      if (exported(statement)) exports.set(declaration.name.text, declaration.name.text);
    }
    if (ts.isFunctionDeclaration(statement) && statement.name) {
      declarations.set(statement.name.text, statement);
      if (exported(statement)) exports.set(statement.name.text, statement.name.text);
    }
    if (ts.isExportDeclaration(statement)) {
      const names = statement.exportClause && ts.isNamedExports(statement.exportClause) ? statement.exportClause.elements : [];
      if (statement.moduleSpecifier) {
        if (!names.length || names.some(name => /^(metadata|generateMetadata)$/.test(name.name.text))) failures.ending++;
      } else for (const name of names) exports.set(name.name.text, name.propertyName?.text ?? name.name.text);
    }
  }
  function title(raw, template = false, seen = new Set()) {
    const node = unwrap(raw);
    if (node && ts.isIdentifier(node) && constants.has(node.text) && !seen.has(node.text)) return title(constants.get(node.text), template, new Set([...seen, node.text]));
    if (node && ts.isConditionalExpression(node)) { title(node.whenTrue, template, seen); title(node.whenFalse, template, seen); return; }
    if (node && ts.isObjectLiteralExpression(node)) {
      let found = false;
      for (const part of node.properties) {
        const key = propertyName(part.name);
        if (ts.isPropertyAssignment(part) && /^(default|absolute|template)$/.test(key ?? '')) { found = true; title(part.initializer, key === 'template', seen); }
        else failures.ending++;
      }
      if (!found) failures.ending++;
      return;
    }
    const literalPart = (raw, visited = new Set()) => {
      const value = unwrap(raw);
      if (value && (ts.isStringLiteralLike(value) || ts.isNumericLiteral(value))) return value.text;
      if (value && ts.isIdentifier(value) && constants.has(value.text) && !visited.has(value.text)) return literalPart(constants.get(value.text), new Set([...visited, value.text]));
      // Unknown content cannot establish a nonempty descriptive label.
      return '';
    };
    const text = node && ts.isStringLiteralLike(node) ? node.text : node && ts.isTemplateExpression(node) ? node.head.text + node.templateSpans.map(part => literalPart(part.expression) + part.literal.text).join('') : '';
    if (!/\S.* · (?:Beirut Time|بيروت تايم)$/.test(text) || (template && !text.includes('%s'))) failures.ending++;
  }
  function object(raw) {
    const node = unwrap(raw);
    if (node && ts.isConditionalExpression(node)) { object(node.whenTrue); object(node.whenFalse); return; }
    if (!node || !ts.isObjectLiteralExpression(node)) { failures.ending++; return; }
    let found = false;
    for (const part of node.properties) {
      if (propertyName(part.name) === 'title') { found = true; title(ts.isPropertyAssignment(part) ? part.initializer : part.name); }
      else if (ts.isSpreadAssignment(part)) failures.ending++;
    }
    if (!found && !allowsMissing) failures.ending++;
  }
  function alwaysReturns(node) {
    if (ts.isReturnStatement(node)) return Boolean(node.expression);
    if (ts.isThrowStatement(node)) return true;
    if (ts.isBlock(node)) return Boolean(node.statements.length && alwaysReturns(node.statements.at(-1)));
    if (ts.isIfStatement(node)) return Boolean(node.elseStatement && alwaysReturns(node.thenStatement) && alwaysReturns(node.elseStatement));
    if (ts.isTryStatement(node)) return (node.finallyBlock && alwaysReturns(node.finallyBlock)) || (alwaysReturns(node.tryBlock) && (!node.catchClause || alwaysReturns(node.catchClause.block)));
    return false;
  }
  if (!exports.has('metadata') && !exports.has('generateMetadata') && !allowsMissing) failures.missing++;
  if (exports.has('metadata')) object(declarations.get(exports.get('metadata')));
  if (exports.has('generateMetadata')) {
    const fn = unwrap(declarations.get(exports.get('generateMetadata')));
    if (!fn || !(ts.isFunctionDeclaration(fn) || ts.isFunctionExpression(fn) || ts.isArrowFunction(fn)) || !fn.body) failures.ending++;
    else if (!ts.isBlock(fn.body)) object(fn.body);
    else {
      const walk = node => {
        if (ts.isReturnStatement(node)) { object(node.expression); return; }
        if (!ts.isFunctionLike(node)) ts.forEachChild(node, walk);
      };
      ts.forEachChild(fn.body, walk);
      if (!allowsMissing && !alwaysReturns(fn.body)) failures.ending++;
    }
  }
  return failures;
}

