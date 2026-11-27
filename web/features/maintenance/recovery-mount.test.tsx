import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {beforeEach,expect,it,vi} from 'vitest';
import {DiagnosisEditor} from './intake/diagnosis-editor';
import {originalOutcome,useScopedOperationJournal,type OperationBinding,type OperationJournal} from './scoped-operation';

const mounted=vi.hoisted(()=>({top:{current:undefined as unknown},capture:false,scope:'signed-in',actor:'buyer' as string|undefined,
  journal:undefined as OperationJournal|undefined,binding:null as OperationBinding|null}));
vi.mock('react',async original=>{
  const react=await original<typeof import('react')>();
  return {...react,useRef:(value:unknown)=>{
    if(mounted.capture) {
      if(mounted.top.current===undefined)mounted.top.current=value;
      return mounted.top;
    }
    return react.useRef(value);
  },useState:(value:unknown)=>mounted.capture?[value,()=>{}]:react.useState(value)};
});
vi.mock('@/shell/locale-context',()=>({useLocale:()=> 'en'}));
vi.mock('@/features/identity/session',()=>({useSession:()=>mounted.actor?{
  access_fingerprint:mounted.scope,principal:{actor:{subject_id:mounted.actor}},
}:null}));
vi.mock('@contracts/contracts-service/test-keys/v1',()=>({validTestKeys:()=>true}));

const preference:OperationBinding={kind:'preference',operation_id:'original',owner:'buyer',record:'request-a',organization:'shop',
  expected_revision:1,source_revision:3};
const diagnosis:OperationBinding={...preference,kind:'diagnosis',owner:'assessor',record:'case-a',source_revision:5};
function Shell({privateEditor=false}:{privateEditor?:boolean}) {
  mounted.capture=true;
  const {journal,binding}=useScopedOperationJournal(mounted.actor);
  mounted.capture=false;mounted.journal=journal;mounted.binding=binding;
  return <>
    {binding&&<p>{binding.operation_id}</p>}
    {mounted.actor&&privateEditor&&<DiagnosisEditor key={mounted.scope} scope={mounted.scope} organization="shop" caseId="case-a"
      intakeRevision={5} available inherited={binding} journal={journal} onDenied={()=>{}}/>}
  </>;
}
const render=(privateEditor=false)=>renderToStaticMarkup(createElement(Shell,{privateEditor}));
beforeEach(()=>{mounted.top.current=undefined;mounted.actor='buyer';mounted.scope='signed-in';});

it('hides a pending buyer preference during reauthorization, then restores only the same buyer original',()=>{
  render();expect(mounted.journal?.begin(preference)).toBe(true);
  mounted.actor=undefined;expect(render()).not.toContain('original');
  mounted.actor='another-buyer';expect(render()).not.toContain('original');
  expect(mounted.journal?.resolve(preference)).toBe(false);
  mounted.actor='buyer';mounted.scope='new-current-scope';
  expect(render()).toContain('original');
  const newer={operation_id:'superseded',buyer_id:'buyer',request_id:'request-a',organization_id:'shop',
    request_revision:3,expected_revision:2,revision:3,opening_permitted:false,no_polish:true};
  expect(originalOutcome(newer,preference)).toBeNull();
  expect(originalOutcome({...newer,operation_id:'original',expected_revision:1,revision:2},preference)).toBe('recorded');
  expect(mounted.journal?.resolve(preference)).toBe(true);
  expect(render()).not.toContain('original');
});

it('does not create a second diagnosis after an uncertain commit and a denied editor remount',()=>{
  mounted.actor='assessor';expect(render(true)).toContain('Review current intake');
  expect(mounted.journal?.begin(diagnosis)).toBe(true);
  mounted.actor=undefined;expect(render(true)).not.toContain('original');
  mounted.actor='assessor';mounted.scope='reauthorized';
  const after=render(true);
  expect(after).toContain('original');
  expect(after).not.toContain('Review current intake');
  const newer={...diagnosis,operation_id:'second',expected_revision:2};
  expect(mounted.journal?.begin(newer)).toBe(false);
  expect(mounted.journal?.resolve(newer)).toBe(false);
  expect(mounted.journal?.resolve(diagnosis)).toBe(true);
  expect(render(true)).toContain('Review current intake');
  expect(mounted.journal?.begin(newer)).toBe(true);
  expect(mounted.journal?.resolve(diagnosis)).toBe(false);
  expect(render(true)).toContain('second');
});
