import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Context } from './draft';
import type { QualityCommand } from '@contracts/contracts-service/quality/v1';

// A minimal host keeps these component checks independent of browser layout.
class Host {
  nodeType = 1;
  nodeName = 'DIV';
  tagName = 'DIV';
  namespaceURI = 'http://www.w3.org/1999/xhtml';
  ownerDocument = documentHost;
  parentNode: Host | null = null;
  childNodes: Host[] = [];
  style = {};
  constructor(public textContent = '') {}
  appendChild(child: Host) { child.parentNode = this; this.childNodes.push(child); return child; }
  removeChild(child: Host) { this.childNodes = this.childNodes.filter(item => item !== child); return child; }
  insertBefore(child: Host, before: Host) { child.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(before), 0, child); return child; }
  setAttribute() {}
  removeAttribute() {}
  addEventListener() {}
  removeEventListener() {}
}
const documentHost = {
  nodeType: 9, addEventListener() {}, removeEventListener() {},
  createElement: () => new Host(),
  createTextNode: (text: string) => Object.assign(new Host(text), { nodeType: 3 }),
  activeElement: null,
};
const controls = vi.hoisted(() => ({ textareas: [] as { value: string; disabled: boolean; onValueChange: (value: string) => void }[], selects: [] as { onValueChange: (value: string) => void }[], buttons: [] as { children: string; disabled?: boolean; onClick?: () => void }[], fingerprint: 'one', locale: 'en' }));
vi.mock('@beirut-time/ui/foundation', () => ({
  Button: (props: typeof controls.buttons[number]) => { controls.buttons.push(props); return null; },
  Card: ({ children }: { children: React.ReactNode }) => children,
  Textarea: (props: typeof controls.textareas[number]) => { controls.textareas.push(props); return null; },
  Select: (props: typeof controls.selects[number]) => { controls.selects.push(props); return null; },
  State: () => null, formatNumber: String,
}));
vi.mock('@/shell/foundation/page', () => ({ PageFrame: ({children}: {children: React.ReactNode}) => children, PageHeader: () => null }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => controls.locale }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: controls.fingerprint }) }));
import QualityView, { type QualityPorts } from './view';

const context: Context = { line_ids: Array.from({length: 6}, (_, i) => String(i)), test_keys: Object.fromEntries(Array.from({length: 6}, (_, i) => [String(i), ['actual']])), job_id:'job', actor_id:'reviewer', organization_id:'business', watch_id:'watch', expected_revision:0, scope_revision:1, work_revision:1, assignment_revision:1, quote_id:'quote', quote_revision:1, policy_revision:1 };

afterEach(() => vi.unstubAllGlobals());
describe('mounted quality form', () => {
  async function mount(submit: QualityPorts['submit'], initial: Partial<QualityPorts> = {}) {
    vi.stubGlobal('document', documentHost);
    vi.stubGlobal('window', { event: undefined, HTMLIFrameElement: class {} });
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    controls.locale = 'en';
    const root = createRoot(new Host() as unknown as HTMLElement);
    let props: QualityPorts = { context, state: 'ready', submit, reload: () => {}, ...initial };
    async function render(update: Partial<QualityPorts> = {}) {
      props = {...props, ...update};
      controls.textareas = []; controls.selects = []; controls.buttons = [];
      await act(async () => root.render(<QualityView {...props}/>));
      controls.textareas = []; controls.selects = []; controls.buttons = [];
      await act(async () => root.render(<QualityView {...props}/>));
    }
    async function fill() {
      const textareas = [...controls.textareas];
      await act(async () => textareas.forEach(field => field.onValueChange('قياس 175 mm 👩🏽‍🔧')));
      await render();
      const selects = [...controls.selects];
      await act(async () => selects.forEach(field => field.onValueChange('pass')));
      await render();
    }
    function currentForm() {
      const container = (root as unknown as { _internalRoot: { containerInfo: Host } })._internalRoot.containerInfo;
      return container.childNodes[0];
    }
    async function send() {
      const form = currentForm();
      const key = Object.keys(form).find(key => key.startsWith('__reactProps'))!;
      const handler = (form as unknown as Record<string, {onSubmit: (event: {preventDefault: () => void}) => void}>)[key].onSubmit;
      await act(async () => handler({preventDefault() {}}));
    }
    await render();
    return { render, fill, send, root, currentForm };
  }
  it('retains pagination, findings and the uncertain command through refresh and language changes', async () => {
    const commands: QualityCommand[] = [];
    const form = await mount(async command => { commands.push(command); throw new Error('connection'); });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send();
    const mountedForm = form.currentForm();
    await form.render({state: 'loading', context: undefined});
    expect(form.currentForm()).toBe(mountedForm);
    await form.render({state: 'unavailable', context: undefined});
    expect(form.currentForm()).toBe(mountedForm);
    expect(controls.textareas.every(field => field.disabled)).toBe(true);
    controls.locale = 'ar';
    await form.render({state: 'ready', context});
    expect(form.currentForm()).toBe(mountedForm);
    expect(controls.textareas).toHaveLength(4);
    expect(controls.textareas[0].value).toBe('قياس 175 mm 👩🏽‍🔧');
    await form.send();
    expect(commands).toHaveLength(2);
    expect(commands[1]).toBe(commands[0]);
    await act(async () => form.root.unmount());
    controls.locale = 'en';
  });
  it('retains the mounted form and operation when context properties are reordered', async () => {
    const commands: QualityCommand[] = [];
    const form = await mount(async command => { commands.push(command); return {state:'pending'}; });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send();
    const node = form.currentForm();
    const reordered = Object.fromEntries(Object.entries(context).reverse()) as Context;
    reordered.test_keys = Object.fromEntries(Object.entries(context.test_keys).reverse());
    controls.locale = 'ar';
    await form.render({context:reordered});
    expect(form.currentForm()).toBe(node);
    expect(controls.textareas[0].value).toBe('قياس 175 mm 👩🏽‍🔧');
    await form.send();
    expect(commands[1]).toBe(commands[0]);
    await act(async () => form.root.unmount());
  });
  it('bounds submission waiting and ignores a late conflicting response after retry', async () => {
    const commands: QualityCommand[] = [];
    let late!: (value: {state:'denied'}) => void;
    const form = await mount(command => {
      commands.push(command);
      return commands.length === 1 ? new Promise(resolve => { late = resolve; }) : Promise.resolve({state:'pending'});
    });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill();
    vi.useFakeTimers();
    try {
      await form.send();
      await form.render();
      expect(controls.buttons.find(button => button.children === 'Retry')!.disabled).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
      await form.render();
      expect(controls.buttons.find(button => button.children === 'Retry')!.disabled).toBe(false);
      await form.send();
      expect(commands[1]).toBe(commands[0]);
      await act(async () => late({state:'denied'}));
      await form.render();
      expect(controls.textareas[0].value).toBe('قياس 175 mm 👩🏽‍🔧');
      expect(controls.buttons.find(button => button.children === 'Retry')!.disabled).toBe(false);
    } finally {
      vi.useRealTimers();
      await act(async () => form.root.unmount());
    }
  });
  it('retries the identical unavailable operation after revalidation', async () => {
    const commands: QualityCommand[] = [];
    const form = await mount(async command => { commands.push(command); return {state:'unavailable'}; });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send();
    await form.render({state:'loading',context:undefined});
    const node = form.currentForm();
    const key = Object.keys(node).find(key=>key.startsWith('__reactProps'))!;
    expect((node as unknown as Record<string, {hidden?: boolean}>)[key].hidden).not.toBe(true);
    expect(controls.textareas.every(field=>field.disabled)).toBe(true);
    await form.render({state:'ready',context});
    await form.send();
    expect(commands).toHaveLength(2);
    expect(commands[1]).toBe(commands[0]);
    await act(async()=>form.root.unmount());
  });
  it('reads 1000 lines in bounded pages using the server total', async () => {
    const page = (offset: number): Context => ({...context,total:1000,
      line_ids:Array.from({length:5},(_,i)=>String(offset+i)),
      test_keys:Object.fromEntries(Array.from({length:5},(_,i)=>[String(offset+i),['actual']]))});
    const reads: number[] = [];
    const form = await mount(async()=>({state:'pending'}), {context:page(0),readPage:async(offset,limit)=>{
      expect(limit).toBe(5); reads.push(offset); return page(offset);
    }});
    await form.fill();
    for(let i=1;i<200;i++) {
      await act(async()=>controls.buttons.find(button=>button.children==='Next')!.onClick!());
      await form.render();
      expect(controls.textareas).toHaveLength(20);
    }
    expect(reads).toHaveLength(199);
    expect(reads[198]).toBe(995);
    await act(async()=>controls.buttons.find(button=>button.children==='Previous')!.onClick!());
    await form.render();
    expect(reads).toHaveLength(199);
    await act(async()=>form.root.unmount());
  }, 20000);
  it('recovers a page timeout without losing findings', async () => {
    const initial = {...context,total:1000,line_ids:['0'],test_keys:{'0':['actual']}};
    const form = await mount(async()=>({state:'pending'}), {context:initial,readPage:()=>new Promise(()=>{})});
    await form.fill();
    vi.useFakeTimers();
    await act(async()=>{ void controls.buttons.find(button=>button.children==='Next')!.onClick!(); });
    await act(async()=>{ await vi.advanceTimersByTimeAsync(1200); });
    vi.useRealTimers();
    await form.render();
    expect(controls.textareas.every(field=>!field.disabled)).toBe(true);
    expect(controls.textareas[0].value).toBe('قياس 175 mm 👩🏽‍🔧');
    expect(controls.buttons.some(button=>button.children==='Next')).toBe(true);
    await act(async()=>form.root.unmount());
  });
  it('clears private findings and the command after confirmed submission denial', async () => {
    const commands: QualityCommand[] = [];
    const form = await mount(async command => { commands.push(command); return {state: 'denied'}; });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send(); await form.render();
    expect(commands).toHaveLength(1);
    expect(form.currentForm()).toBeUndefined();
    expect(controls.textareas).toHaveLength(0);
    await form.render({state: 'unavailable', context: undefined});
    await form.render({state: 'ready', context});
    expect(form.currentForm()).toBeUndefined();
    await form.render({context: {...context, assignment_revision: 2}});
    expect(controls.textareas.every(field => field.value === '')).toBe(true);
    await act(async () => form.root.unmount());
  });
  it('clears private context and uncertain operations when current access is denied', async () => {
    const commands: QualityCommand[] = [];
    const form = await mount(async command => { commands.push(command); return {state: 'pending'}; });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send();
    expect(commands).toHaveLength(1);
    await form.render({state: 'denied', context});
    expect(form.currentForm()).toBeUndefined();
    expect(controls.textareas).toHaveLength(0);
    expect(controls.selects).toHaveLength(0);
    await form.render({state: 'loading', context: undefined});
    expect(form.currentForm()).toBeUndefined();
    await form.render({state: 'unavailable'});
    expect(form.currentForm()).toBeUndefined();
    await form.render({state: 'ready', context});
    expect(controls.textareas).toHaveLength(20);
    expect(controls.textareas.every(field => field.value === '')).toBe(true);
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send();
    expect(commands).toHaveLength(2);
    expect(commands[1].operation_id).not.toBe(commands[0].operation_id);
    await act(async () => form.root.unmount());
  });
  it('unlocks correction only after confirmed rejection and creates a new operation', async () => {
    const commands: QualityCommand[] = [];
    const form = await mount(async command => { commands.push(command); return {state: 'rejected'}; });
    await form.fill();
    await act(async () => controls.buttons.find(button => button.children === 'Next')!.onClick!());
    await form.render(); await form.fill(); await form.send(); await form.render();
    expect(controls.textareas.every(field => !field.disabled)).toBe(true);
    await act(async () => controls.textareas[0].onValueChange('Corrected reading'));
    await form.send();
    expect(commands[1].operation_id).not.toBe(commands[0].operation_id);
    expect(commands[1].lines[5].tests[0].actual).toBe('Corrected reading');
    await form.render({state: 'denied'});
    await form.render({state: 'ready'});
    expect(controls.textareas[0].value).toBe('');
    await act(async () => form.root.unmount());
  });
});
