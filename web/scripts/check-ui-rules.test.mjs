import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import ts from 'typescript';
import { ESLint } from 'eslint';
import nextVitals from 'eslint-config-next/core-web-vitals';
import { SEMANTIC_PLUGIN, SEMANTIC_RULES } from './ui-source.mjs';
import { cleanupBoundary, cleanupLedgerHashes } from './check-foundation-boundary.mjs';
import { INTERFACE_CHECKS, LEDGER, ROOT, census, committedHistory, cssDeclarations, hashSource, inspectSource, ledgerRegressions, measure, measureReference, metadataIssues, motionTokenMs, regressions, rulebookIssues, sourceFiles, verifyMeasurements } from './check-ui-rules.mjs';

const layers = new Set(['--z-skip-link']);
const css = (source, file = 'web/features/review/styles.css') => inspectSource(file, source, { layers });
const jsx = (source, file = 'web/features/review/view.tsx') => inspectSource(file, source, { layers });
const view = body => `export default function Review() { return ${body}; }`;
const faceImport = 'import { State } from "@beirut-time/ui";';
const canonicalFaceImport = 'import { State } from "@beirut-time/ui/foundation";';
const canonicalButton = 'import { Button } from "@beirut-time/ui/foundation"; export default () => <Button>Review</Button>;';
const quietError = `${faceImport} function Unused() { return <State kind="error" />; } export default function Error() { return <p>Could not load</p>; }`;
const choices = view('<div role="group" aria-label="View">{["one", "two"].map(value => <button key={value} aria-pressed={selected === value} onClick={() => setSelected(value)} className={selected === value ? "bg-primary" : "bg-muted"}>{value}</button>)}</div>');
const safeCss = '.review { color: var(--foreground); font-weight: var(--ds-weight-black); }';
const safeJsx = view('<button type="button" className="outline-none focus-visible:ring-2 text-foreground hover:bg-accent">Review</button>');
const pairedOutline = '.review { outline:none; } .review:focus-visible { outline:2px solid var(--ring); }';
const pairedRing = '.review { outline:0 solid transparent; } .review:focus-visible { box-shadow:0 0 0 2px var(--ring); }';
const explicitTransitions = '.review { transition:transform var(--ds-motion-fast) var(--ease-out-soft), opacity var(--ds-motion-fast) var(--ease-out-soft); }';
const bulkPaint = 'export function paint(el:HTMLElement){Object.assign(el.style,{color:"#fff",transition:"all 200ms ease-in",transform:"scale(0)",zIndex:"999"});}';
const bulkTokens = 'export function paint(el:HTMLElement){Object.assign(el.style,{color:"var(--foreground)",transition:"transform var(--ds-motion-fast) var(--ease-out-soft), opacity var(--ds-motion-fast) var(--ease-out-soft)",transform:"translateY(4px)",opacity:"1",zIndex:"var(--z-skip-link)"});}';
const canonicalMotion = readFileSync(join(ROOT, 'web/styles/bt-motion.css'), 'utf8');
const foldStart = canonicalMotion.indexOf('  :where(:where(.bt-fold)) {');
const foldEnd = canonicalMotion.indexOf('  :where(:where(.bt-pressable)) {', foldStart);
assert.ok(foldStart >= 0 && foldEnd > foldStart, 'The real shared fold must exist.');
const canonicalFold = `@layer components {\n${canonicalMotion.slice(foldStart, foldEnd)}}`;
const validCurve = ':root { --bt-ease-response: cubic-bezier(.23,1,.32,1); } @layer components { :where(.bt-menu) { transition-timing-function: var(--bt-ease-response); } }';

/** Every accepted evasive form from the independent review, plus canonical cases.
 * Each record is physically measured as both a new file and a changed legacy file;
 * these are not merely direct regular-expression assertions. */
const probes = [
  ['spaced priority', 'css', '.review { color: var(--foreground) ! IMPORTANT; }', 'bt-force-priority'],
  ['rendered priority', 'tsx', view('<style>{".review { color: var(--foreground) !important; }"}</style>'), 'bt-force-priority'],
  ['private layer', 'css', '.review { --bt-layer-invented: 999; z-index: var(--bt-layer-invented); }', 'bt-stack-escape'],
  ['numeric layer fallback', 'tsx', view('<div style={{zIndex: "var(--bt-layer-missing, 999)"}} />'), 'bt-stack-escape'],
  ['named signed colours', 'css', '.review { color: red; background: hsl(-30 50% 50%); }', 'bt-palette-inline'],
  ['inline named colour', 'tsx', view('<div style={{color: "white"}} />'), 'bt-palette-inline'],
  ['palette utility literal', 'tsx', view('<div className="bg-[#fff]" />'), 'bt-palette-inline'],
  ['SVG literal paint', 'tsx', view('<svg aria-hidden="true" fill="#fff"><path /></svg>'), 'bt-palette-inline'],
  ['literal token fallback', 'css', '.review { color: var(--foreground, #fff); }', 'bt-palette-inline'],
  ['interpolated hex', 'tsx', 'const suffix = "FFF"; export default () => <div style={{color: `#FFF${suffix}`}} />;', 'bt-palette-inline'],
  ['uppercase response curve', 'css', '.review { transition-timing-function: EASE-IN; }', 'bt-slow-start'],
  ['template duration', 'tsx', 'const curve = "var(--bt-ease-out)"; export default () => <div style={{transition: `opacity 200ms ${curve}`}} />;', 'bt-motion-literal'],
  ['uppercase time unit', 'css', '.review { transition-duration: 150MS; }', 'bt-motion-literal'],
  ['variant spin only', 'tsx', view('<span className="motion-safe:animate-spin" />'), 'bt-loop-detour'],
  ['variant pulse only', 'tsx', view('<span className="data-[busy]:motion-safe:animate-pulse" />'), 'bt-loop-detour'],
  ['inline transition property', 'tsx', view('<div style={{transitionProperty: "all"}} />'), 'bt-property-sweep'],
  ['uppercase sweep', 'css', '.review { transition: ALL var(--bt-motion-fast); }', 'bt-property-sweep'],
  ['inline zero scale', 'tsx', view('<div style={{transform: "scale(0)"}} />'), 'bt-vanishing-scale'],
  ['exponent zero scale', 'css', '.review { transform: scale(0e0); }', 'bt-vanishing-scale'],
  ['inline layout transition', 'tsx', view('<div style={{transition: "height var(--bt-motion-fast)"}} />'), 'bt-reflow-motion'],
  ['layout utility transition', 'tsx', view('<div className="transition-[height]" />'), 'bt-reflow-motion'],
  ['hover utility travel', 'tsx', view('<span className="hover:scale-105" />'), 'bt-touch-hover'],
  ['rendered keyframes', 'tsx', view('<style>{"@keyframes review { from { opacity: 0 } to { opacity: 1 } }"}</style>'), 'bt-motion-owner'],
  ['inline private fold', 'tsx', view('<div style={{gridTemplateRows: "0fr"}} />'), 'bt-fold-detour'],
  ['inline viewport unit', 'tsx', view('<div style={{height: "100vh"}} />'), 'bt-viewport-unit'],
  ['dynamic outline reset', 'tsx', 'export default function Review({extra}) { return <button className={`${extra} outline-none`}>Review</button>; }', 'bt-focus-lost'],
  ['offset without width', 'tsx', view('<button className="outline-none focus-visible:ring-offset-2">Review</button>'), 'bt-focus-lost'],
  ['colour without width', 'tsx', view('<button className="outline-none focus-visible:ring-ring">Review</button>'), 'bt-focus-lost'],
  ['zero focus width', 'tsx', view('<button className="outline-none focus-visible:ring-0">Review</button>'), 'bt-focus-lost'],
  ['decimal zero focus width', 'tsx', view('<button className="outline-none focus-visible:ring-[.0px]">Review</button>'), 'bt-focus-lost'],
  ['no focus outline', 'tsx', view('<button className="outline-none focus-visible:outline-none">Review</button>'), 'bt-focus-lost'],
  ['double inset shorthand', 'css', '.review { position: fixed; inset: 0 0; }', 'bt-modal-detour'],
  ['four inset edges', 'css', '.review { position: fixed; top: 0; right: 0; bottom: 0; left: 0; }', 'bt-modal-detour'],
  ['inline full screen', 'tsx', view('<div style={{position: "fixed", inset: 0}} />'), 'bt-modal-detour'],
  ['invented active fill', 'tsx', view('<button aria-pressed={selected === "one"} onClick={() => choose("one")} className={selected ? "review-selected" : "review-idle"}>One</button>'), 'bt-choice-detour'],
  ['mapped native choices', 'tsx', choices, 'bt-choice-detour'],
  ['private reexport', 'tsx', 'export { Button } from "@beirut-time/ui/button";', 'bt-control-detour'],
  ['relative private import', 'tsx', 'import { Button } from "../../../packages/ui/src/button"; export default () => <Button>Review</Button>;', 'bt-control-detour'],
  ['unused error face', 'tsx', quietError, 'bt-boundary-quiet', 'web/app/review/error.tsx'],
  ['shadowed unused error face', 'tsx', `${faceImport} const content = <p>Quiet</p>; function Unused() { const content = <State kind="error"/>; return content; } export default () => content;`, 'bt-boundary-quiet', 'web/app/review/error.tsx'],
  ['conditional quiet error', 'tsx', `${faceImport} export default function Error() { if (failed) return <State kind="error" />; return <p>Quiet</p>; }`, 'bt-boundary-quiet', 'web/app/review/error.tsx'],
  ['unused root alert', 'tsx', 'function Unused() { return <p role="alert">Error</p>; } export default () => <html><body>Quiet</body></html>;', 'bt-boundary-quiet', 'web/app/global-error.tsx'],
  ['conditional root alert', 'tsx', 'export default function Error() { if (failed) return <p role="alert">Error</p>; return <p>Quiet</p>; }', 'bt-boundary-quiet', 'web/app/global-error.tsx'],
  ['click only box', 'tsx', view('<div onClick={() => {}}>Review</div>'), 'jsx-a11y'],
  ['unnamed control label', 'tsx', view('<label><input /></label>'), 'jsx-a11y'],
  ['unassociated label', 'tsx', view('<label>Review</label>'), 'jsx-a11y'],
  ['raw numeric stack', 'css', '.review { z-index: 999; }', 'bt-stack-escape'],
  ['dependency import', 'tsx', 'import { scene } from "three"; export default () => null;', 'bt-runtime-weight'],
  ['off system timing', 'tsx', view('<span className="duration-700" />'), 'bt-timing-detour'],
  ['private CSS frames', 'css', '@keyframes review { from { opacity: 0 } to { opacity: 1 } }', 'bt-motion-owner'],
  ['opaque consumer style', 'tsx', 'export default ({paint}) => <div style={paint} />;', 'bt-style-opaque'],
  ['missing page title', 'tsx', view('<p>Review</p>'), 'bt-title-absent', 'web/app/review/page.tsx'],
  ['wrong title ending', 'tsx', 'export const metadata = {title: "Review - Beirut Time"}; export default () => <p>Review</p>;', 'bt-title-format', 'web/app/review/page.tsx'],
  ['empty template label', 'tsx', 'const name=""; export const metadata={title:`${name} · Beirut Time`}; export default () => <p>Review</p>;', 'bt-title-format', 'web/app/review/page.tsx'],
  ['long owner time', 'css', ':root { --bt-motion-review: 800ms; }', 'bt-time-budget', 'web/styles/tokens.css'],
  ['silent shared state', 'tsx', 'export function State({kind}) { return <div role={kind === "loading" ? "status" : undefined}>Review</div>; }', 'bt-state-alert-gap', 'packages/ui/src/index.tsx'],
  // Second RETURN: ordinary syntax is inspected; hard indirection needs review.
  ['time-first all shorthand', 'css', '.review { transition: var(--ds-motion-fast) all; }', 'bt-property-sweep'],
  ['time-first height shorthand', 'css', '.review { transition: var(--ds-motion-fast) height; }', 'bt-reflow-motion'],
  ['comment-separated zero', 'css', '.review { transform: scale(/*start*/0); }', 'bt-vanishing-scale'],
  ['logical border layout', 'css', '.review { transition: border-inline-start-width var(--ds-motion-fast); }', 'bt-reflow-motion'],
  ['literal constant curve', 'css', '.review { transition: opacity var(--ds-motion-fast) linear; }', 'bt-motion-literal', undefined, '.review { animation: turn var(--bt-motion-fast) var(--bt-ease-constant); }'],
  ['embedded reordered shorthand', 'tsx', view('<style>{".review { transition: var(--ds-motion-fast) all; }"}</style>'), 'bt-property-sweep'],
  ['inline commented zero', 'tsx', view('<div style={{transform:"scale(/*start*/0)"}} />'), 'bt-vanishing-scale'],
  ['HWB function', 'css', '.review { color: hwb(0 0% 0%); }', 'bt-palette-inline'],
  ['profile colour function', 'css', '.review { color: color(display-p3 1 0 0); }', 'bt-palette-inline'],
  ['inline HWB', 'tsx', view('<div style={{color:"hwb(0 0% 0%)"}}/>'), 'bt-palette-inline'],
  ['inline profile colour', 'tsx', view('<div style={{color:"color(display-p3 1 0 0)"}}/>'), 'bt-palette-inline'],
  ['imperative paint', 'ts', 'export function paint(el:HTMLElement){el.style.color="#fff";}', 'bt-palette-inline'],
  ['imperative all transition', 'ts', 'export function paint(el:HTMLElement){el.style.transition="all 200ms ease-in";}', 'bt-property-sweep'],
  ['imperative literal duration', 'ts', 'export function paint(el:HTMLElement){el.style.transition="all 200ms ease-in";}', 'bt-motion-literal'],
  ['imperative ease-in', 'ts', 'export function paint(el:HTMLElement){el.style.transition="all 200ms ease-in";}', 'bt-slow-start'],
  ['imperative zero scale', 'ts', 'export function paint(el:HTMLElement){el.style.transform="scale(0)";}', 'bt-vanishing-scale'],
  ['imperative layer number', 'ts', 'export function paint(el:HTMLElement){el.style.zIndex="999";}', 'bt-stack-escape'],
  ['imperative setProperty', 'ts', 'export function paint(el:HTMLElement){el.style.setProperty("color","#fff");}', 'bt-palette-inline'],
  ['imperative cssText', 'ts', 'export function paint(el:HTMLElement){el.style.cssText="color:#fff";}', 'bt-palette-inline'],
  ['WAAPI layout frame', 'ts', 'import {readMotionToken} from "./motion-tokens"; export function move(el:HTMLElement){el.animate([{height:"0px",transform:"scale(0)",color:"#fff"},{height:"100px"}],{duration:readMotionToken("--ds-motion-fast")});}', 'bt-reflow-motion', 'packages/ui/src/motion-tokens.ts'],
  ['WAAPI zero frame', 'ts', 'el.animate([{transform:"scale(0)"},{transform:"none"}],{duration:readMotionToken("--ds-motion-fast")});', 'bt-vanishing-scale'],
  ['WAAPI colour frame', 'ts', 'el.animate([{color:"#fff"},{color:"var(--foreground)"}],{duration:readMotionToken("--ds-motion-fast")});', 'bt-palette-inline'],
  ['WAAPI property arrays', 'ts', 'el.animate({height:["0px","100px"]},{duration:readMotionToken("--ds-motion-fast")});', 'bt-reflow-motion'],
  ['opaque animation frames', 'ts', 'el.animate(frames,{duration:readMotionToken("--ds-motion-fast")});', 'bt-style-opaque'],
  ['opaque animation options', 'ts', 'el.animate([{opacity:0},{opacity:1}],{...options});', 'bt-style-opaque'],
  ['opaque imperative value', 'ts', 'el.style.transform=unknownTransform;', 'bt-style-opaque'],
  ['opaque custom style value', 'ts', 'el.style.setProperty("--bt-motion-local",unknownDuration);', 'bt-style-opaque'],
  ['JSX props object spread', 'tsx', 'const props={style:{color:"#fff"}}; export default ()=><div {...props}/>;', 'bt-style-opaque', undefined, view('<div {...{title:"Review","data-kind":"watch"}}/>')],
  ['JSX class spread', 'tsx', view('<button {...{className:"outline-none"}}>Review</button>'), 'bt-style-opaque'],
  ['JSX visibility spread', 'tsx', view('<div {...{"aria-hidden":true}} role="alert">Review</div>'), 'bt-style-opaque'],
  ['unknown JSX spread', 'tsx', 'export default ({props})=><div {...props}/>;', 'bt-style-opaque'],
  ['reassigned let paint', 'tsx', 'let paint="var(--foreground)"; paint="#fff"; export default ()=><div style={{color:paint}}/>;', 'bt-style-opaque', undefined, 'const paint="var(--foreground)"; export default ()=><div style={{color:paint}}/>;'],
  ['conditional mutable paint', 'tsx', 'let paint="var(--foreground)"; if(changed)paint="#fff"; export default ()=><div style={{color:paint}}/>;', 'bt-style-opaque'],
  ['mutable class binding', 'tsx', 'let choice="text-foreground"; choice="outline-none"; export default ()=><button className={choice}>Review</button>;', 'bt-style-opaque'],
  ['mutated referenced style object', 'tsx', 'const paint={color:"var(--foreground)"}; paint.color="#fff"; export default ()=><div style={paint}/>;', 'bt-style-opaque'],
  ['disabled-only focus width', 'tsx', view('<button className="outline-none disabled:focus-visible:ring-2">Review</button>'), 'bt-focus-lost'],
  ['hover-only focus width', 'tsx', view('<button className="outline-none hover:focus-visible:ring-2">Review</button>'), 'bt-focus-lost'],
  ['CSS focused reset', 'css', '.review:focus-visible { outline:none; }', 'bt-focus-lost', undefined, '.review:focus-visible { outline:none; box-shadow:0 0 0 2px var(--ring); }'],
  ['inline outline reset', 'tsx', view('<button style={{outline:"none"}}>Review</button>'), 'bt-focus-lost', undefined, view('<button style={{outline:"none"}} className="focus-visible:ring-2">Review</button>')],
  ['State variable shadow', 'tsx', '"use client"; import {State} from "@beirut-time/ui"; type Face=typeof State; export default function Error(){const State:Face=()=> <p>Quiet</p>; return <State kind="error" title="Error" body="Try again"/>;}', 'bt-style-opaque', 'web/app/review/error.tsx'],
  ['State parameter shadow', 'tsx', `${faceImport} export default function Error({State}) {return <State kind="error"/>;}`, 'bt-style-opaque', 'web/app/review/error.tsx'],
  ['JS JSX palette', 'js', view('<div style={{color:"#fff"}} onClick={()=>{}}>Review</div>'), 'bt-palette-inline'],
  ['JS JSX semantics', 'js', view('<div style={{color:"#fff"}} onClick={()=>{}}>Review</div>'), 'jsx-a11y'],
  ['module JS semantics', 'mjs', view('<div onClick={()=>{}}>Review</div>'), 'jsx-a11y'],
  ['common JS semantics', 'cjs', 'module.exports=function(){return <div onClick={()=>{}}>Review</div>;};', 'jsx-a11y', undefined, 'module.exports=function(){return <button>Review</button>;};'],
  // Base focus resets, shorthand defaults and bulk style writes.
  ['base outline reset', 'css', '.review { outline:none; }', 'bt-focus-lost', undefined, pairedOutline],
  ['base shorthand zero', 'css', '.review { outline:0 solid transparent; }', 'bt-focus-lost', undefined, pairedRing],
  ['base shorthand none', 'css', '.review { outline:2px none var(--ring); }', 'bt-focus-lost', undefined, pairedOutline],
  ['base outline style', 'css', '.review { outline-style:none; }', 'bt-focus-lost', undefined, pairedOutline],
  ['base outline width', 'css', '.review { outline-width:0rem; }', 'bt-focus-lost', undefined, pairedRing],
  ['rendered base reset', 'tsx', view('<style>{".review { outline:none; }"}</style>'), 'bt-focus-lost', undefined, view(`<style>{${JSON.stringify(pairedOutline)}}</style>`)],
  ['disabled CSS pair', 'css', '.review { outline:none; } .review:disabled:focus-visible { outline:2px solid var(--ring); }', 'bt-focus-lost', undefined, pairedOutline],
  ['different media focus pair', 'css', '.review { outline:none; } @media (pointer:fine) { .review:focus-visible { outline:2px solid var(--ring); } }', 'bt-focus-lost', undefined, pairedRing],
  ['implicit all shorthand', 'css', '.review { transition:var(--ds-motion-fast) var(--ease-out-soft); }', 'bt-property-sweep', undefined, explicitTransitions],
  ['first implicit comma item', 'css', '.review { transition:var(--ds-motion-fast) var(--ease-out-soft), opacity var(--ds-motion-fast); }', 'bt-property-sweep', undefined, explicitTransitions],
  ['last implicit comma item', 'css', '.review { transition:transform var(--ds-motion-fast), var(--ds-motion-fast) var(--ease-out-soft); }', 'bt-property-sweep', undefined, explicitTransitions],
  ['inline implicit all', 'tsx', view('<div style={{transition:"var(--ds-motion-fast) var(--ease-out-soft)"}}/>'), 'bt-property-sweep', undefined, view('<div style={{transition:"transform var(--ds-motion-fast) var(--ease-out-soft), opacity var(--ds-motion-fast) var(--ease-out-soft)"}}/>')],
  ['inline implicit comma item', 'tsx', view('<div style={{transition:"opacity var(--ds-motion-fast), var(--ds-motion-fast) var(--ease-out-soft)"}}/>'), 'bt-property-sweep', undefined, view('<div style={{transition:"none"}}/>')],
  ['rendered implicit all', 'tsx', view('<style>{".review { transition:var(--ds-motion-fast) var(--ease-out-soft); }"}</style>'), 'bt-property-sweep', undefined, view(`<style>{${JSON.stringify(explicitTransitions)}}</style>`)],
  ['imperative implicit all', 'ts', 'el.style.transition="var(--ds-motion-fast) var(--ease-out-soft)";', 'bt-property-sweep', undefined, bulkTokens],
  ['unreadable property list', 'css', '.review { transition-property:var(--bt-transition-properties); }', 'bt-style-opaque', undefined, '.review { transition:none; }'],
  ['bulk literal colour', 'ts', bulkPaint, 'bt-palette-inline', undefined, bulkTokens],
  ['bulk all properties', 'ts', bulkPaint, 'bt-property-sweep', undefined, bulkTokens],
  ['bulk literal motion', 'ts', bulkPaint, 'bt-motion-literal', undefined, bulkTokens],
  ['bulk slow start', 'ts', bulkPaint, 'bt-slow-start', undefined, bulkTokens],
  ['bulk vanishing scale', 'ts', bulkPaint, 'bt-vanishing-scale', undefined, bulkTokens],
  ['bulk raw layer', 'ts', bulkPaint, 'bt-stack-escape', undefined, bulkTokens],
  ['bulk unknown object', 'ts', 'export function paint(el:HTMLElement,paint:object){Object.assign(el.style,paint);}', 'bt-style-opaque', undefined, bulkTokens],
  ['bulk spread object', 'ts', 'Object.assign(el.style,{...paint,opacity:"1"});', 'bt-style-opaque', undefined, bulkTokens],
  ['bulk spread source', 'ts', 'Object.assign(el.style,...paints);', 'bt-style-opaque', undefined, bulkTokens],
  ['bulk later literal source', 'ts', 'Object.assign(el.style,{opacity:"1"},{color:"#fff"});', 'bt-palette-inline', undefined, bulkTokens],
  ['bulk element style access', 'ts', 'Object.assign(el["style"],{color:"#fff"});', 'bt-palette-inline', undefined, bulkTokens],
  ['bulk implicit all', 'ts', 'Object.assign(el.style,{transition:"var(--ds-motion-fast) var(--ease-out-soft)"});', 'bt-property-sweep', undefined, bulkTokens],
  ['legacy motion selector', 'css', '.pg-popover { opacity:1; }', 'bt-motion-legacy'],
  ['legacy motion class variant', 'tsx', view('<span className="hover:pg-nav-icon"/>'), 'bt-motion-legacy'],
  ['legacy frame consumer', 'css', '.review { animation:pg-fadeOut var(--bt-motion-fast) var(--bt-ease-out); }', 'bt-motion-legacy'],
  ['legacy frame definition', 'css', '@keyframes pg-fadeOut { to { opacity:0; } }', 'bt-motion-legacy', 'web/styles/bt-motion.css'],
  ['legacy frame alias', 'css', '.review { --bt-local-frame:pg-fadeOut; animation:var(--bt-local-frame) var(--bt-motion-fast) var(--bt-ease-out); }', 'bt-motion-legacy'],
  ['canonical slow-start token', 'css', ':root { --bt-ease-delayed: ease-in; } @layer components { :where(.bt-menu) { transition-timing-function: var(--bt-ease-delayed); } }', 'bt-slow-start', 'web/styles/bt-motion.css', validCurve],
  ['owner private row transition', 'css', '@layer components { :where(.bt-private-panel) { grid-template-rows:20px; transition:grid-template-rows var(--bt-motion-menu) var(--bt-ease-out); } }', 'bt-reflow-motion', 'web/styles/bt-motion.css', canonicalFold],
  ['owner broader fold selector', 'css', canonicalFold.replace(':where(:where(.bt-fold)) {', ':where(:where(.bt-fold), .bt-private-panel) {'), 'bt-reflow-motion', 'web/styles/bt-motion.css', canonicalFold],
  ['owner wrong fold value', 'css', canonicalFold.replace('grid-template-rows: 0fr', 'grid-template-rows: 20px'), 'bt-reflow-motion', 'web/styles/bt-motion.css', canonicalFold],
  ['owner wrong open fold value', 'css', canonicalFold.replace('grid-template-rows: 1fr', 'grid-template-rows: auto'), 'bt-reflow-motion', 'web/styles/bt-motion.css', canonicalFold],
  ['owner broader fold transition', 'css', canonicalFold.replace('grid-template-rows var(--bt-motion-menu) var(--bt-ease-out)', 'grid-template-rows var(--bt-motion-menu) var(--bt-ease-out), opacity var(--bt-motion-fast) var(--bt-ease-out)'), 'bt-reflow-motion', 'web/styles/bt-motion.css', canonicalFold],
  ['owner wrong fold context', 'css', canonicalFold.replace('@layer components {', '@layer utilities {'), 'bt-reflow-motion', 'web/styles/bt-motion.css', canonicalFold],
  ['copied fold row transition', 'css', canonicalFold, 'bt-reflow-motion'],
  ['new root control import', 'tsx', 'import { Button } from "@beirut-time/ui"; export default () => <Button>Review</Button>;', 'bt-control-detour', undefined, canonicalButton],
  ['aliased root control import', 'tsx', 'import { Button as Action } from "@beirut-time/ui"; export default () => <Action>Review</Action>;', 'bt-control-detour', undefined, canonicalButton],
  ['root namespace import', 'tsx', 'import * as UI from "@beirut-time/ui"; export default () => <UI.Button>Review</UI.Button>;', 'bt-control-detour', undefined, canonicalButton],
  ['root control reexport', 'ts', 'export { Button } from "@beirut-time/ui";', 'bt-control-detour', undefined, 'export { Button } from "@beirut-time/ui/foundation";'],
  ['root wildcard reexport', 'ts', 'export * from "@beirut-time/ui";', 'bt-control-detour', undefined, 'export * from "@beirut-time/ui/foundation";'],
  ['compatibility control import', 'tsx', 'import { Button } from "@/shell/primitives"; export default () => <Button>Review</Button>;', 'bt-control-detour', undefined, canonicalButton],
  ['dynamic root control import', 'ts', 'export async function load(){return import("@beirut-time/ui");}', 'bt-control-detour', undefined, 'export async function load(){return import("@beirut-time/ui/foundation");}'],
  ['relative compatibility import', 'tsx', 'import {Button} from "../shell/primitives"; export default()=> <Button>Review</Button>;', 'bt-control-detour', 'web/features/relative-probe.tsx', canonicalButton],
  ['same directory compatibility import', 'tsx', 'import {Button} from "./primitives"; export default()=> <Button>Review</Button>;', 'bt-control-detour', 'web/shell/probe.tsx', canonicalButton],
  ['relative extension compatibility import', 'tsx', 'import {Button as Action} from "../shell/primitives.tsx"; export default()=> <Action>Review</Action>;', 'bt-control-detour', 'web/features/relative-probe.tsx', canonicalButton],
  ['relative index compatibility import', 'tsx', 'import {Button} from "../shell/primitives/index.tsx"; export default()=> <Button>Review</Button>;', 'bt-control-detour', 'web/features/relative-probe.tsx', canonicalButton],
  ['relative compatibility namespace', 'tsx', 'import * as UI from "../shell/primitives"; export default()=> <UI.Button>Review</UI.Button>;', 'bt-control-detour', 'web/features/relative-probe.tsx', canonicalButton],
  ['relative compatibility reexport', 'ts', 'export {Button as Action} from "./primitives.tsx";', 'bt-control-detour', 'web/shell/probe.ts', 'export {Button as Action} from "@beirut-time/ui/foundation";'],
  ['relative compatibility star reexport', 'ts', 'export * from "./primitives/index";', 'bt-control-detour', 'web/shell/probe.ts', 'export * from "@beirut-time/ui/foundation";'],
  ['relative compatibility dynamic load', 'ts', 'export async function load(){return import("./primitives");}', 'bt-control-detour', 'web/shell/probe.ts', 'export async function load(){return import("@beirut-time/ui/foundation");}'],
  ['extension compatibility alias', 'tsx', 'import {Button} from "@/shell/primitives.tsx"; export default()=> <Button>Review</Button>;', 'bt-control-detour', undefined, canonicalButton],
  ['normalized relative compatibility import', 'tsx', 'import {Button} from "../shell/../shell/primitives"; export default()=> <Button>Review</Button>;', 'bt-control-detour', 'web/features/relative-probe.tsx', canonicalButton],
];
function controlFor(file, extension) {
  if (file === 'packages/ui/src/index.tsx') return 'export function State({kind}) { return <div role={kind === "error" ? "alert" : "status"}>Review</div>; }';
  if (file === 'web/app/global-error.tsx') return view('<html lang="en"><body><p role="alert">Review</p></body></html>');
  if (file.endsWith('/error.tsx')) return `${canonicalFaceImport} export default () => <State kind="error" title="Review" body="Review" />;`;
  if (file.endsWith('/page.tsx')) return 'export const metadata = {title: "J · Beirut Time"}; export default () => <p>Review</p>;';
  if (extension === 'ts') return 'export function review(el:HTMLElement){el.style.color="var(--foreground)";}';
  return extension === 'css' ? safeCss : safeJsx;
}

test('all review escapes fail as physical new and changed files, with passing controls', async () => {
  const directory = mkdtempSync(join(ROOT, '.bt-interface-probe-'));
  const exercised = new Set();
  const write = (file, text) => { mkdirSync(dirname(join(directory, file)), {recursive: true}); writeFileSync(join(directory, file), text); };
  try {
    for (const [name, extension, bad, check, explicit, good] of probes) {
      const file = explicit ?? `web/features/review/probe.${extension}`;
      const token = 'web/styles/tokens.css';
      write(token, ':root { --z-skip-link: 110; }');
      const before = '/* accepted legacy snapshot */\n' + (file === token ? ':root { --bt-motion-old: 800ms; }' : extension === 'css' ? '.old { color: #fff; }' : extension === 'ts' ? 'export function old(el:HTMLElement){el.style.color="white";}' : view('<div style={{color: "white"}} />'));
      for (const state of ['new', 'changed']) {
        // First write and measure the accepted bytes, then really change the file.
        // A changed legacy file receives no allowance, even for the same counter.
        let accepted = {};
        if (state === 'changed') {
          write(file, before);
          accepted = {[file]: (await measure(directory))[file]};
          assert.ok(Object.keys(accepted[file].counts).length, `${name}: valid legacy debt snapshot`);
        }
        write(file, bad);
        const current = await measure(directory);
        const failures = verifyMeasurements(current, accepted, {initial: accepted, accepted});
        assert.ok((current[file]?.counts[check] ?? 0) > 0, `${name} (${state}): did not emit ${check}: ${JSON.stringify(current[file])}`);
        assert.ok(failures.some(line => line.startsWith(`${file}: ${check} `)), `${name} (${state}): ${failures.join('\n')}`);
        exercised.add(check);
        write(file, good ?? controlFor(file, extension));
        const control = await measure(directory);
        assert.deepEqual(verifyMeasurements(control, {}, {initial: accepted, accepted}), [], `${name} (${state}) positive control`);
      }
      if (file !== token) unlinkSync(join(directory, file));
    }
    assert.deepEqual([...exercised].sort(), Object.keys(INTERFACE_CHECKS).sort(), 'Every registered check must be exercised, not merely happen to occur in main.');
  } finally { rmSync(directory, {recursive: true, force: true}); }
});

test('tokens, semantic utilities, local literals outside styling, and comments do not invent debt', () => {
  assert.deepEqual(css(safeCss), {});
  assert.deepEqual(css('.a { background: url("/red.png"); }'), {});
  assert.deepEqual(css('.a { color: rgb(var(--bt-channels)); background: color-mix(in oklab, var(--card), transparent); }'), {});
  assert.deepEqual(css('.a { color: oklch(from var(--primary) calc(l - .1) c h); }'), {});
  assert.deepEqual(jsx('export function Frame({alt,...props}){return <img {...props} alt={alt}/>;}', 'packages/ui/src/image-frame.tsx'), {});
  assert.deepEqual(jsx(safeJsx), {});
  assert.deepEqual(jsx(view('<svg aria-hidden="true" fill="currentColor"><path /></svg>')), {});
  assert.deepEqual(jsx('// <div style={{color:"red"}}/>\nconst description = "black; 200ms; !important"; export {};'), {});
  assert.deepEqual(jsx('export { Button } from "@beirut-time/ui/foundation";'), {});
  assert.deepEqual(jsx(canonicalButton), {});
  assert.deepEqual(css('.a { z-index: var(--z-skip-link); }'), {});
  assert.ok(css('.a { z-index: var(--bt-layer-missing); }')['bt-stack-escape']);
  assert.ok(css('.a { --z-skip-link: 400; }')['bt-stack-escape']);
  assert.deepEqual(css('@media (hover: hover) and (pointer: fine) { .a:hover { transform: translateY(-1px); } }'), {});
  assert.deepEqual(jsx('const kind = "save"; export default () => <button className={kind === "save" ? "outline-none focus-visible:ring-2" : "outline-none focus-visible:outline-2"}>Save</button>;'), {});
  assert.deepEqual(css('@keyframes reveal { from { opacity: 0; transform: scale(.95); } to { opacity: 1; transform: none; } }', 'web/styles/bt-motion.css'), {});
  assert.deepEqual(css(canonicalFold, 'web/styles/bt-motion.css'), {});
  assert.deepEqual(jsx(view('<div className="fixed inset-0" />'), 'packages/ui/src/dialog.tsx'), {});
  assert.ok(jsx(view('<div className="fixed inset-0" />'), 'packages/ui/src/anything.tsx')['bt-modal-detour']);
  assert.ok(jsx('export default function Wrapped({className}) { return <span className={unknownClass(className)} />; }', 'packages/ui/src/anything.tsx')['bt-style-opaque']);
  assert.deepEqual(jsx(view('<button className="bt-toggle-item-active">Review</button>'), 'packages/ui/src/segmented.tsx'), {});
});

test('base focus pairs, explicit transition properties and token-based bulk writes remain clean', () => {
  for (const source of [pairedOutline, pairedRing, '.review { outline:none; box-shadow:0 0 0 2px var(--ring); }', '.review { outline:none; } .review:focus { outline:2px solid var(--ring); }', `@media (pointer:fine) { ${pairedOutline} }`, explicitTransitions, '.review { transition:none; }', '.review { transition:var(--ds-motion-fast) opacity var(--ease-out-soft), transform var(--ds-motion-fast); }']) assert.deepEqual(css(source), {}, source);
  assert.deepEqual(jsx(view('<div style={{transition:"none"}}/>')), {});
  assert.deepEqual(jsx(bulkTokens, 'web/features/review/style.ts'), {});
  assert.deepEqual(jsx('Object.assign(record,{color:"#fff",transition:"all 200ms ease-in"});', 'web/features/review/record.ts'), {});
  assert.equal(css('.review { transition:var(--ds-motion-fast) var(--ease-out-soft), var(--ds-motion-fast) var(--ease-out-soft); }')['bt-property-sweep'], 2);
  assert.ok(css('.review { outline:none; } .unrelated:focus-visible { outline:2px solid var(--ring); }')['bt-focus-lost']);
  assert.ok(css('.review { outline:none; } .review:focus-visible { outline:0 solid var(--ring); }')['bt-focus-lost']);
  assert.ok(css('.review { outline:none; } .review:focus-visible { outline:2px; }')['bt-focus-lost']);
});

test('semantic census reuses the framework flat-config plugin rather than a second copy', () => {
  const configured = nextVitals.find(entry => entry.plugins?.['jsx-a11y'])?.plugins['jsx-a11y'];
  assert.ok(configured);
  assert.equal(SEMANTIC_PLUGIN, configured);
  assert.equal(SEMANTIC_RULES, configured.configs.recommended.rules);
});

test('CSS parsing handles nested context, quoted punctuation and case-sensitive variable names', () => {
  const entries = cssDeclarations('/* false {a:b} */ @media (hover: hover) { .a:hover { background: url("a;{b}.png"); --MixedCase: var(--CaseSensitive); transform: translateY(-1px); } }');
  assert.equal(entries[1].prop, '--MixedCase');
  assert.equal(entries[1].value, 'var(--CaseSensitive)');
  assert.deepEqual(entries[2].context, ['@media (hover: hover)', '.a:hover']);
  for (const query of ['(hover: hover)', '(hover: hover), (pointer: fine)', '(hover: hover) or (pointer: fine)', 'not all and (hover: hover) and (pointer: fine)', '(hover: hover) and (pointer: fine), print']) assert.ok(css(`@media ${query} { .a:hover { transform: translateY(-1px); } }`)['bt-touch-hover']);
});

test('duration arithmetic fails closed and script motion consumes the same tokens', () => {
  assert.equal(motionTokenMs('0.15s'), 150);
  assert.equal(motionTokenMs('150MS'), 150);
  assert.equal(motionTokenMs('calc((100ms + 0.1s) / 2)'), 100);
  assert.equal(motionTokenMs('calc(var(--a) * 2)', {'--a': '120ms'}), 240);
  assert.equal(motionTokenMs('var(--missing, 200ms)'), 200);
  for (const input of ['var(--missing)', 'calc(100ms + 2)', 'calc(100ms * 2ms)', '-1ms', 'max(100ms, 200ms)', 'calc(1s / 0)']) assert.equal(motionTokenMs(input), null);
  assert.equal(motionTokenMs('var(--a)', {'--a': 'var(--a)'}), null);
  assert.ok(css(':root { --bt-motion-theme: var(--missing); }', 'web/styles/tokens.css')['bt-time-budget']);
  assert.equal(jsx('element.animate([], {duration:200, easing:"cubic-bezier(.2,0,0,1)"});')['bt-motion-literal'], 2);
  assert.deepEqual(jsx('element.animate([], {duration:readMotionToken("--bt-motion-fast"), easing:readEasingToken("--bt-ease-out")});'), {});
  assert.deepEqual(jsx('element.animate([{opacity:0,transform:"translateY(4px)"},{opacity:1,transform:"none"}], {duration:readMotionToken("--ds-motion-fast"),easing:readEasingToken("--bt-ease-out")});', 'web/features/review/move.ts'), {});
  assert.deepEqual(jsx('export function drag(el:HTMLElement, distance:number){el.style.transform=`translateY(${distance}px)`;}', 'web/features/review/drag.ts'), {});
  assert.deepEqual(jsx('export function drag(el:HTMLElement, distance:unknown){el.style.translate=`${Number(distance)}px 0px`;}', 'web/features/review/drag.ts'), {});
  assert.deepEqual(jsx('el.style.setProperty("color","var(--foreground)"); el.style.zIndex="var(--z-skip-link)";', 'web/features/review/style.ts'), {});
});

const meta = source => metadataIssues(ts.createSourceFile('page.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX));
test('one-letter and one-grapheme titles are valid; missing/opaque/conditional bad paths are not', () => {
  for (const title of ['J · Beirut Time', 'ن · بيروت تايم', '👨‍👩‍👧‍👦 · Beirut Time', 'Watches · Beirut Time']) assert.deepEqual(meta(`export const metadata = {title: "${title}"};`), {missing: 0, ending: 0});
  assert.deepEqual(meta('const TITLE="J · Beirut Time"; const value={title:TITLE}; export {value as metadata};'), {missing:0, ending:0});
  for (const source of ['export const metadata = {title:" · Beirut Time"};', 'export const metadata = {title:"  · Beirut Time"};', 'export const metadata={title:titleFor("J")};', 'export {metadata} from "./metadata";', 'export function generateMetadata(){if(ok()) return {title:"J · Beirut Time"};}', 'export function generateMetadata(){return {title: ok()?"J · Beirut Time":"Wrong"};}']) assert.ok(meta(source).ending, source);
  assert.ok(meta('import {name} from "./name"; export const metadata={title:`${name} · Beirut Time`};').ending);
  assert.deepEqual(meta('const name="J"; export const metadata={title:`${name} · Beirut Time`};'), {missing:0, ending:0});
  assert.equal(meta('export default () => null;').missing, 1);
});

test('error evidence follows every returned path; shared-State alert behavior remains explicit debt', () => {
  assert.ok(jsx(quietError, 'web/app/review/error.tsx')['bt-boundary-quiet']);
  assert.ok(jsx('export default function Error(){ const hidden = <p role="alert">Error</p>; return <p>Quiet</p>; }', 'web/app/global-error.tsx')['bt-boundary-quiet']);
  const actual = readFileSync(join(ROOT, 'packages/ui/src/index.tsx'), 'utf8');
  assert.ok(jsx(actual, 'packages/ui/src/index.tsx')['bt-state-alert-gap']);
});

const record = (source, counts) => ({sha256: hashSource(source), counts});
test('hash isolation and latest-accepted history forbid reducing then restoring debt', () => {
  const original = {'old.tsx': record('original', {'bt-motion-literal':2, 'bt-loop-detour':1})};
  const reduced = {'old.tsx': record('original', {'bt-motion-literal':1})};
  const oldBytes = {'old.tsx': record('original', {'bt-motion-literal':2, 'bt-loop-detour':1})};
  assert.deepEqual(ledgerRegressions(reduced, original), []);
  assert.ok(verifyMeasurements(oldBytes, original, {initial: original, accepted: reduced}).some(line => line.includes('cannot grow or return')));
  assert.ok(verifyMeasurements(oldBytes, original, {initial: original, accepted: {}}).some(line => line.includes('cannot be added or replaced')));
  assert.ok(ledgerRegressions({'old.tsx': record('changed', {'bt-motion-literal':1})}, original).length);
  assert.ok(regressions({'old.tsx': record('changed', {'bt-motion-literal':1})}, original).some(line => line.includes('changed file must be clean')));
  assert.ok(regressions({'new.tsx': record('original', {'bt-motion-literal':1})}, original).length);
  assert.ok(regressions(oldBytes, original, true).length);
  assert.deepEqual(verifyMeasurements({'old.tsx':record('fixed', {})}, {}, {initial: original, accepted: reduced}), []);
  // Committed file/rule deletion, then reintroduction with the original bytes/ledger.
  assert.ok(verifyMeasurements(oldBytes, original, {initial: original, accepted:{}}).length);
  assert.ok(ledgerRegressions({'old.tsx': record('original', {'bt-loop-detour':1})}, reduced).length);
});

test('the single committed cleanup cannot admit later edits, copied paths, count growth or retired findings', async () => {
  const file = 'web/styles/foundation.css', pair = cleanupBoundary(file);
  assert.ok(pair && pair.before !== pair.after);
  const history = committedHistory(), ledger = JSON.parse(readFileSync(join(ROOT,LEDGER),'utf8'));
  const initial = {[file]:history.initial[file]}, accepted = {[file]:history.accepted[file]}, active = {[file]:ledger[file]};
  assert.deepEqual(cleanupLedgerHashes(initial),active);
  assert.deepEqual(ledgerRegressions(active,initial),[]);
  assert.ok(ledgerRegressions(active,{}).length,'A deleted file cannot return through the cleanup');
  const growth = structuredClone(active);growth[file].counts['bt-motion-literal'] = 1;
  assert.ok(ledgerRegressions(growth,initial).some(line=>line.includes('cannot grow or return')));
  const reduced = structuredClone(active);delete reduced[file].counts['bt-focus-lost'];
  assert.ok(ledgerRegressions(active,reduced).some(line=>line.includes('cannot grow or return')));
  const restoredRoot = {'web/app/layout.tsx':history.initial['web/app/layout.tsx']};
  assert.ok(ledgerRegressions(restoredRoot,ledger).length,'The retired root entry cannot return');
  const directory = mkdtempSync(join(ROOT,'.bt-cleanup-probe-'));
  const write = (path,text)=>{mkdirSync(dirname(join(directory,path)),{recursive:true});writeFileSync(join(directory,path),text);};
  try {
    const source = readFileSync(join(ROOT,file),'utf8');assert.equal(hashSource(source),pair.after);
    write(file,source);assert.deepEqual(verifyMeasurements(await measure(directory),active,{initial,accepted}),[]);
    write(file,source+'\n/* later edit */');
    assert.ok(verifyMeasurements(await measure(directory),active,{initial,accepted}).some(line=>line.includes('changed file must be clean')));
    const forged = {[file]:record(source+'\n/* later edit */',active[file].counts)};
    assert.ok(ledgerRegressions(forged,initial).length,'Rehashing the later edit is refused');
    write('web/features/review/copied.css',source);
    assert.ok((await measure(directory))['web/features/review/copied.css'].counts['bt-motion-legacy']);
    assert.equal(cleanupBoundary('web/features/review/copied.css'),undefined);
  } finally {rmSync(directory,{recursive:true,force:true});}
});

test('rulebook synchronization is bidirectional, including advertised bare names and every emitted key', () => {
  const law = readFileSync(join(ROOT, 'docs/frontend-rules.md'), 'utf8');
  assert.deepEqual(rulebookIssues(law, Object.keys(INTERFACE_CHECKS)), []);
  const fake = law.replace('`bt-fold-detour`', '`bt-fold-detour`; gate missing-rule-check');
  assert.ok(rulebookIssues(fake).some(line => line.includes('missing-rule-check')));
  assert.ok(rulebookIssues(law.replace('`bt-fold-detour`', '`nonexistent-check`')).length);
  assert.ok(rulebookIssues(law, ['invented-check']).length);
});

test('main-derived bootstrap and both committed ceilings agree with the real measured tree', async () => {
  const ledger = JSON.parse(readFileSync(join(ROOT, LEDGER), 'utf8'));
  const initial = await measureReference();
  assert.deepEqual(ledgerRegressions(ledger, initial), []);
  const history = committedHistory() ?? {initial, accepted:initial};
  assert.deepEqual(verifyMeasurements(await measure(), ledger, history), []);
  const files = sourceFiles();
  for (const file of ['packages/ui/src/image-frame.tsx', 'web/shell/shell.tsx', 'web/lib/brand.ts', 'web/features/discovery/styles.css']) assert.ok(files.includes(file));
  assert.ok(!files.some(file => /node_modules|\.test\.|\/fixtures\//.test(file)));
  assert.ok(Object.keys(census()).length > 100);
});

test('raw images are errors and the one root lint command fails a planted shared-package warning', async () => {
  const linter = new ESLint({cwd:ROOT, overrideConfigFile:join(ROOT,'web/eslint.config.mjs')});
  const [image] = await linter.lintText('export function ReviewImage(){return <img src="/demo/watches/review.webp" alt="Review"/>;}', {filePath:join(ROOT,'packages/ui/src/image-rule-probe.tsx')});
  assert.equal(image.messages.find(message => message.ruleId === '@next/next/no-img-element')?.severity, 2);
  const probe = join(ROOT, 'packages/ui/src/lint-threshold-probe.ts');
  assert.equal(existsSync(probe), false);
  const run = () => spawnSync(process.execPath, [join(ROOT,'web/node_modules/eslint/bin/eslint.js'),'--config','web/eslint.config.mjs','web','packages/ui/src','--max-warnings','0'], {cwd:ROOT, encoding:'utf8', timeout:60_000});
  try {
    writeFileSync(probe, '/* eslint @typescript-eslint/no-unused-vars: "warn" */\nconst unusedReviewValue=1; export {};\n');
    const failed = run(); assert.equal(failed.status, 1, failed.stdout + failed.stderr);
    assert.match(failed.stdout, /packages\/ui\/src\/lint-threshold-probe\.ts/); assert.match(failed.stdout, /warning/);
  } finally { unlinkSync(probe); }
  const clean = run(); assert.equal(clean.status, 0, clean.stdout + clean.stderr);
  assert.equal(JSON.parse(readFileSync(join(ROOT,'web/package.json'),'utf8')).scripts.lint, 'cd .. && web/node_modules/.bin/eslint --config web/eslint.config.mjs web packages/ui/src --max-warnings 0');
});
