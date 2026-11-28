import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import fixtures from '../../../../packages/contracts-trust/private-inspection/fixtures.json';

const hooks = vi.hoisted(()=>({values:[] as unknown[],index:0,locale:'en' as 'en'|'ar'}));
vi.mock('react',async original=>({...await original<typeof import('react')>(),
  useState:(initial:unknown)=>{const i=hooks.index++;if(!(i in hooks.values))hooks.values[i]=initial;return [hooks.values[i],(value:unknown)=>{hooks.values[i]=typeof value==='function'?value(hooks.values[i]):value;}];},
  useRef:(initial:unknown)=>({current:initial}),
}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>hooks.locale}));
const submit = vi.hoisted(()=>vi.fn());
vi.mock('../../../../web/features/private-inspection/api',async original=>({...await original<typeof import('../../../../web/features/private-inspection/api')>(),submitInspection:submit}));
import { InspectionForm } from '../../../../web/features/private-inspection/view';
import type { Workspace } from '../../../../web/features/private-inspection/api';
import { copy } from '../../../../web/features/private-inspection/copy';

type Node = ReactElement<Record<string, unknown>>;
function nodes(node:unknown):Node[] {
  if(Array.isArray(node))return node.flatMap(nodes);
  if(!node || typeof node!=='object' || !('props' in node))return [];
  const element=node as Node;
  return [element,...nodes(element.props.children)];
}
function form(workspace:Workspace) {
  hooks.index=0;
  return InspectionForm({access:'test-scope',workspace,available:true,refresh:vi.fn(),exit:vi.fn(),deny:vi.fn()});
}
const workspace:Workspace = {...fixtures.success.source,schema_version:'private-inspection.v1',expected_revision:0,current_state:null};
function reset() {hooks.values=[];hooks.locale='en';submit.mockReset();}
function findings(tree:Node) {
  const all=nodes(tree);
  (all.find(n=>n.props.label===copy.en.reason)!.props.onValueChange as (v:string)=>void)('Actual test findings');
  (all.find(n=>n.props.label===copy.en.evidence)!.props.onCheckedChange as (v:boolean)=>void)(true);
}
async function send(tree:Node) {
  (tree.props.onSubmit as (e:unknown)=>void)({preventDefault:()=>{}});
  await Promise.resolve();await Promise.resolve();
}

describe('inspection review bindings',()=>{
  it.each(['watch_revision','assignment_revision','source_revision','expected_revision','checklist_revision'] as const)('requires renewed review after %s changes',async key=>{
    reset();findings(form(workspace));
    const changed={...workspace,[key]:workspace[key]+1};
    const tree=form(changed);
    await send(tree);expect(submit).not.toHaveBeenCalled();
    const renew=nodes(tree).find(n=>n.props.children===copy.en.reviewAgain)!;
    (renew.props.onClick as ()=>void)();
    form(changed);
    expect(hooks.values[0]).toEqual(['inconclusive','inconclusive','inconclusive','inconclusive']);
    expect(hooks.values[1]).toBe('');expect(hooks.values[2]).toBe(false);
  });
  it('detects changed evidence and preserves an uncertain command across refresh and language change',async()=>{
    reset();findings(form(workspace));submit.mockRejectedValue(new Error('test lost response'));
    await send(form(workspace));
    const original=submit.mock.calls[0][1];
    hooks.locale='ar';
    const tree=form({...workspace,source_revision:2,evidence_refs:[]});
    await send(tree);
    expect(submit.mock.calls[1][1]).toEqual(original);
    expect(original.source_revision).toBe(1);
    expect(original.reason).toBe('Actual test findings');
  });
  it('blocks changed evidence without losing findings on language change',async()=>{
    reset();findings(form(workspace));hooks.locale='ar';
    await send(form({...workspace,evidence_refs:[]}));
    expect(submit).not.toHaveBeenCalled();
    expect(hooks.values[1]).toBe('Actual test findings');
    expect(hooks.values[2]).toBe(true);
  });
  it.each(['en','ar'] as const)('shows every checklist name in %s',locale=>{
    reset();hooks.locale=locale;
    const html=renderToStaticMarkup(form(workspace));
    for(const item of ['identity','movement','case','provenance'] as const)expect(html).toContain(`<p>${copy[locale][item]}</p>`);
  });
});
