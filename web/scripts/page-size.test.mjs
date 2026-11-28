import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { chmod, mkdir, mkdtemp, readFile, rename, rm, symlink, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { bindComparisonApproval, buildMeasurement, comparePageSizes, comparisonApproval, emittedPageSizes, parseMeasurement } from './check-page-size.mjs';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)),'..');
const measurement = (commit,pages)=>({schema:1,unit:'gzip-bytes',commit:commit.repeat(40),tree:'c'.repeat(40),buildId:'tiny-fixture',pages});
test('size comparison is byte-exact, coverage complete, no old/generic growth approval',()=>{
  const base = measurement('a',{'/internal/page':100,'/internal/components':100}), head = measurement('b',{'/internal/page':101,'/internal/components':99,'/internal/notes':50});
  const failed = comparePageSizes(base,head);assert.equal(failed.passed,false);assert.equal(failed.errors.length,2);
  const approval = bindComparisonApproval({baseCommit:base.commit,reason:'A bounded reviewed change.',pages:{'/internal/page':1,'/internal/notes':50}},base.commit,head.commit);
  assert.throws(()=>bindComparisonApproval({...approval},base.commit,head.commit));
  assert.equal(comparePageSizes(base,head,approval).passed,true);assert.equal(comparePageSizes(base,{...head,pages:{...head.pages,'/internal/notes':51}},approval).passed,false);
  assert.throws(()=>comparePageSizes(base,head,{...approval,headCommit:base.commit}));assert.throws(()=>comparePageSizes(base,head,{...approval,pages:{'/unknown':100}}));
  assert.equal(comparePageSizes(base,{...head,pages:{'/internal/page':100}}).passed,true);
  for (const value of [NaN,-1,Infinity,1.5,'100']) assert.throws(()=>parseMeasurement(measurement('a',{'/internal/page':value})));
});
test('tiny emitted artifacts de-duplicate real chunks and reject missing, escaping and symbolic paths',async()=>{
  const root = await mkdtemp(join(ROOT,'.size-probe-'));
  try {await mkdir(join(root,'.next/diagnostics'),{recursive:true});await mkdir(join(root,'.next/static/chunks'),{recursive:true});
    const js = 'export const value = 1;';await writeFile(join(root,'.next/static/chunks/a.js'),js);
    const entry = {route:'/internal/page',firstLoadUncompressedJsBytes:js.length,firstLoadChunkPaths:['.next/static/chunks/a.js','.next/static/chunks/a.js']};
    const stats = value=>writeFile(join(root,'.next/diagnostics/route-bundle-stats.json'),JSON.stringify(value));
    await stats([entry]);assert.deepEqual(await emittedPageSizes(root),{'/internal/page':gzipSync(js,{level:9}).byteLength});
    await stats([entry,entry]);await assert.rejects(()=>emittedPageSizes(root),/duplicate/);
    await stats([{...entry,firstLoadChunkPaths:['.next/missing.js']}]);await assert.rejects(()=>emittedPageSizes(root));
    await writeFile(join(root,'outside.js'),js);await stats([{...entry,firstLoadChunkPaths:['outside.js']}]);await assert.rejects(()=>emittedPageSizes(root),/escapes/);
    await symlink(join(root,'outside.js'),join(root,'.next/static/chunks/escape.js'));await stats([{...entry,firstLoadChunkPaths:['.next/static/chunks/escape.js']}]);await assert.rejects(()=>emittedPageSizes(root),/symlink/);
    await stats([]);await assert.rejects(()=>emittedPageSizes(root),/diagnostics/);
  } finally {await rm(root,{recursive:true,force:true});}
});
test('quick invocation cannot accidentally start a production build',async()=>{await assert.rejects(()=>buildMeasurement(ROOT,false),/--allow-build/);});
test('real Git approval lookup and default web CLI bind additions, refuse history changes and never recycle prior approval',async()=>{
  const root = await mkdtemp(join(ROOT,'.size-probe-')), web = join(root,'web');
  const originalPath = process.env.PATH;
  try {
    // Tiny Git objects only: no build, branch update or project commit.
    const realGit = execFileSync('which',['git'],{encoding:'utf8'}).trim();
    const env = {...process.env,GIT_CONFIG_NOSYSTEM:'1',GIT_CONFIG_GLOBAL:'/dev/null',GIT_AUTHOR_NAME:'Size fixture',GIT_AUTHOR_EMAIL:'size@example.invalid',GIT_COMMITTER_NAME:'Size fixture',GIT_COMMITTER_EMAIL:'size@example.invalid'};
    const git = (...args)=>execFileSync(realGit,args,{cwd:root,env,encoding:'utf8'}).trim();
    git('init','--quiet');
    const probe = join(root,'.git/probe'), bin = join(probe,'bin'), trace = join(probe,'git.jsonl');
    await mkdir(bin,{recursive:true});await mkdir(join(web,'scripts'),{recursive:true});await mkdir(join(web,'perf/approvals'),{recursive:true});
    const script = join(web,'scripts/check-page-size.mjs');await writeFile(script,await readFile(join(ROOT,'scripts/check-page-size.mjs')));
    const priorFile = join(web,'perf/approvals/prior.json'), addedFile = join(web,'perf/approvals/growth.json');
    const priorSource = JSON.stringify({baseCommit:'0'.repeat(40),reason:'Earlier synthetic comparison.',pages:{'/internal/page':1}});
    await writeFile(priorFile,priorSource);
    const snapshot = parent=>{git('add','--all');return git('commit-tree',git('write-tree'),...(parent ? ['-p',parent] : []),'-m','Synthetic size snapshot');};
    const base = snapshot(), approval = {baseCommit:base,reason:'This synthetic comparison only.',pages:{'/internal/page':1}};
    await writeFile(addedFile,JSON.stringify(approval));const head = snapshot(base);
    const sizes = (commit,bytes)=>({schema:1,unit:'gzip-bytes',commit,tree:git('rev-parse',`${commit}^{tree}`),buildId:'synthetic-no-build',pages:{'/internal/page':bytes}});
    const basePath = join(probe,'base.json'), headPath = join(probe,'head.json');
    const wrapper = join(bin,'git');
    await writeFile(wrapper,`#!/usr/bin/env node\nimport {appendFileSync} from 'node:fs';\nimport {spawnSync} from 'node:child_process';\nappendFileSync(${JSON.stringify(trace)},JSON.stringify({cwd:process.cwd(),args:process.argv.slice(2)})+'\\n');\nconst result=spawnSync(${JSON.stringify(realGit)},process.argv.slice(2),{stdio:'inherit'});\nif(result.error) throw result.error;\nprocess.exit(result.status ?? 1);\n`);
    await chmod(wrapper,0o755);process.env.PATH = `${bin}:${originalPath}`;
    const compare = async(before,after,from=100,to=100)=>{
      await writeFile(basePath,JSON.stringify(sizes(before,from)));await writeFile(headPath,JSON.stringify(sizes(after,to)));
      // Normal web-directory invocation: the script derives ROOT; no --root override.
      return spawnSync(process.execPath,[script,'compare','--base',basePath,'--head',headPath],{cwd:web,env:{...env,PATH:process.env.PATH},encoding:'utf8'});
    };
    await writeFile(addedFile,'not the committed approval');
    assert.deepEqual(comparisonApproval(web,base,head),{...approval,headCommit:head});
    const allowed = await compare(base,head,100,101);assert.equal(allowed.status,0,allowed.stderr);assert.equal(JSON.parse(allowed.stdout).passed,true);
    const overflow = await compare(base,head,100,102);assert.equal(overflow.status,1,overflow.stderr);assert.equal(JSON.parse(overflow.stdout).passed,false);
    await writeFile(addedFile,JSON.stringify(approval));
    for (const change of ['edit','delete','rename']) {
      if (change === 'edit') await writeFile(priorFile,priorSource+'\n');
      if (change === 'delete') await rm(priorFile);
      if (change === 'rename') await rename(priorFile,join(web,'perf/approvals/renamed.json'));
      const changed = snapshot(head), refused = await compare(base,changed);
      assert.equal(refused.status,1,`${change}: ${refused.stdout}`);assert.match(refused.stderr,/append-only/);
      if (change === 'rename') await rm(join(web,'perf/approvals/renamed.json'));
      await writeFile(priorFile,priorSource);
    }
    await writeFile(join(web,'later.txt'),'Another synthetic change.');const later = snapshot(head);
    assert.equal(comparisonApproval(web,head,later),null);
    const reused = await compare(head,later,101,102);assert.equal(reused.status,1,reused.stderr);assert.equal(JSON.parse(reused.stdout).passed,false);
    assert.throws(()=>comparePageSizes(sizes(base,100),sizes(later,101),{...approval,headCommit:head}),/exact comparison/);
    await writeFile(join(web,'perf/approvals/wrong-base.json'),JSON.stringify(approval));
    const wrongBase = snapshot(later);assert.throws(()=>comparisonApproval(web,later,wrongBase),/Invalid size approval source/);
    const calls = (await readFile(trace,'utf8')).trim().split('\n').map(line=>JSON.parse(line)), diffs = calls.filter(call=>call.args[0] === 'diff');
    assert.ok(diffs.length >= 8);
    for (const call of diffs) {
      assert.equal(call.cwd,web,'Approval lookup must exercise the normal web cwd');
      assert.deepEqual(call.args.slice(0,4),['diff','--name-status','--no-renames','-z']);
      assert.deepEqual(call.args.slice(6),['--',':(top)web/perf/approvals/'],'Approval directory must be repository-top anchored');
    }
    assert.ok(calls.some(call=>call.cwd === web && call.args[0] === 'show' && call.args[1] === `${head}:web/perf/approvals/growth.json`),'Read approval bytes from the exact head, not the working file');
  } finally {if (originalPath === undefined) delete process.env.PATH;else process.env.PATH = originalPath;await rm(root,{recursive:true,force:true});}
});
