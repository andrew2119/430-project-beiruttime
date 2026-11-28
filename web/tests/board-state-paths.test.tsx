import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Children, isValidElement, type ReactElement } from 'react';
import { Button, Dialog, DialogContent, DropdownMenuContent, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem, Input, Popover, PopoverContent, ScrollRegion, Select, Sheet, SheetContent, State, type SelectProps } from '@beirut-time/ui/foundation';
import { SelectOptions } from '../../packages/ui/src/foundation/select-options';
import { clearToasts, currentToasts } from '../../packages/ui/src/foundation/toast-store';
import { createDeliveryGate } from '../internal/components/select-delivery';
import { boardBoundary } from '../internal/components/boundary';
import { MenuExample, PopupExample, SurfaceCases, ToastCase } from '../internal/components/surface-cases';
const hooks = vi.hoisted(()=>({slots:[] as unknown[],cursor:0,dir:'ltr'}));
vi.mock('react',async()=>{
  const real = await vi.importActual<typeof import('react')>('react');
  return {...real,useId:()=> 'review-field',useCallback:(fn:unknown)=>fn,useEffect:()=>{},useLayoutEffect:()=>{},useContext:()=>({dir:hooks.dir,lang:hooks.dir === 'rtl' ? 'ar' : 'en'}),useSyncExternalStore:(_subscribe:unknown,get:()=>unknown)=>get(),useRef:(initial:unknown)=>{const at = hooks.cursor++;if (!(at in hooks.slots)) hooks.slots[at] = {current:initial};return hooks.slots[at];},useState:(initial:unknown)=>{const slots = hooks.slots,at = hooks.cursor++;if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;return [slots[at],(next:unknown)=>{slots[at] = typeof next === 'function' ? next(slots[at]) : next;}];}};
});
type View = ReactElement<Record<string,unknown>>;
function elements(view:unknown):View[] {if (!isValidElement(view)) return [];const node = view as View;return [node,...Children.toArray(node.props.children as never).flatMap(elements)];}
function render(run:()=>unknown) {hooks.cursor = 0;return run() as View;}
function button(view:View,label:string) {const found = elements(view).find(node=>node.type === Button && node.props.children === label);expect(found,label).toBeDefined();return found!;}
function click(node:View,extra:Record<string,unknown> = {}) {expect(node.props.disabled).not.toBe(true);(node.props.onClick as (event:unknown)=>void)({detail:1,...extra});}
beforeEach(()=>{
  hooks.slots = [];hooks.cursor = 0;hooks.dir = 'ltr';vi.stubGlobal('window',{matchMedia:()=>({matches:false})});vi.stubGlobal('document',{documentElement:{}});vi.stubGlobal('getComputedStyle',()=>({getPropertyValue:()=> '120ms'}));
});
afterEach(()=>{clearToasts();vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
describe('actual prototype component/controller paths, not catalogue metadata or a mounted DOM',()=>{
  it('passes actual usual/worst surface props into the named read/wide/four-sheet and menu/popup components',()=>{
    for (const locale of ['en','ar'] as const) for (const mode of ['demo','worst','empty','one','thousand'] as const) {
      const example = boardBoundary(mode,locale);
      for (const kind of ['dialog','wide','bottom','end','responsive','phone'] as const) {
        hooks.slots = [];const view = render(()=>SurfaceCases({mode,locale,copy:example.copy,initialSurface:kind}));
        const root = elements(view).find(node=>(node.type === Dialog || node.type === Sheet) && node.props.open === true)!;expect(root,kind).toBeDefined();
        const content = elements(root).find(node=>node.type === DialogContent || node.type === SheetContent)!;expect(content.props.title).toBe(example.title);expect(content.props.description).toBe(example.copy.surfaceBody);expect(content.props.closeLabel).toBe(example.copy.close);expect(elements(content).find(node=>typeof node.props.reopen === 'function')?.props.description).toBe(example.description);
        if (kind === 'dialog' || kind === 'wide') expect(content.props.size).toBe(kind === 'wide' ? 'wide' : 'read');else expect(content.props.form).toBe(kind);
      }
      hooks.slots = [];const popup = render(()=>PopupExample({copy:example.copy,initialOpen:true}));expect(popup.props.open).toBe(true);expect(elements(popup).find(node=>node.type === PopoverContent)?.props.label).toBe(example.copy.popupLabel);expect(elements(popup).some(node=>node.type === 'p' && node.props.children === example.copy.surfaceBody)).toBe(true);
      hooks.slots = [];const menu = render(()=>MenuExample({copy:example.copy,initialOpen:true}));expect(menu.props.open).toBe(true);expect(elements(menu).find(node=>node.type === DropdownMenuContent)?.props.label).toBe(example.copy.menuLabel);expect(elements(menu).some(node=>node.type === DropdownMenuItem && node.props.disabled === true)).toBe(true);expect(elements(menu).some(node=>node.type === DropdownMenuItem && node.props.destructive === true)).toBe(true);expect(elements(menu).filter(node=>node.type === DropdownMenuRadioItem)).toHaveLength(3);
      (elements(menu).find(node=>node.type === DropdownMenuRadioGroup)!.props.onValueChange as (value:string)=>void)('deliver');const changed = render(()=>MenuExample({copy:example.copy,initialOpen:true}));expect(elements(changed).find(node=>node.type === DropdownMenuRadioGroup)?.props.value).toBe('deliver');
    }
  });
  it('the actual ScrollRegion attachment names a tab stop only for its overflowing axes',()=>{
    const flags = new Set<string>(), box = {scrollHeight:100,clientHeight:100,scrollWidth:100,clientWidth:100,tabIndex:9,toggleAttribute:(name:string,on:boolean)=>{if (on) flags.add(name);else flags.delete(name);}};
    const attach = (axis:'vertical'|'horizontal'|'both')=>{const view = render(()=>ScrollRegion({label:'Review content',axis,children:'Content'}));(view.props.ref as (node:unknown)=>void)(box);};
    attach('both');expect(box.tabIndex).toBe(-1);expect(flags.size).toBe(0);box.scrollHeight = 500;attach('vertical');expect(box.tabIndex).toBe(0);expect(flags.has('data-overflow-y')).toBe(true);expect(flags.has('data-overflow-x')).toBe(false);
    box.scrollWidth = 300;attach('horizontal');expect(flags.has('data-overflow-y')).toBe(false);expect(flags.has('data-overflow-x')).toBe(true);attach('both');expect(flags.has('data-overflow-y')).toBe(true);expect(flags.has('data-overflow-x')).toBe(true);box.scrollHeight = 100;box.scrollWidth = 100;attach('both');expect(box.tabIndex).toBe(-1);expect(flags.size).toBe(0);
  });
  it('drives the real Select pending→failed→retry→shared-code path without a fabricated market answer',async()=>{
    const copy = boardBoundary('worst','ar').copy, gate = createDeliveryGate(), onValueChange = vi.fn();
    const props:SelectProps = {id:'review-select',label:copy.displayName,value:'kept',onValueChange,options:[{value:'kept',label:copy.primary}],messages:copy.select,loadGate:gate.wait};
    const draw = ()=>render(()=>Select(props));let view = draw();const trigger = elements(view).find(node=>node.type === Button && node.props.role === 'combobox')!;
    (trigger.props.onPointerDown as (event:unknown)=>void)({button:0,ctrlKey:false,preventDefault:vi.fn()});view = draw();expect(gate.current()).toBe('waiting');expect(elements(view).some(node=>node.props.role === 'status' && node.props.children === copy.select.loading)).toBe(true);
    gate.fail();await vi.waitFor(()=>expect(elements(draw()).find(node=>node.type === State && node.props.kind === 'error')).toBeDefined());view = draw();const failure = elements(view).find(node=>node.type === State && node.props.kind === 'error')!;expect(failure.props.title).toBe(copy.select.errorTitle);click(button(failure,copy.select.retry));expect(gate.current()).toBe('waiting');expect(elements(draw()).some(node=>node.props.role === 'status')).toBe(true);
    gate.release();await vi.waitFor(()=>expect(draw().type).toBe(SelectOptions));view = draw();expect(view.props.value).toBe('kept');expect(view.props.options).toBe(props.options);expect(onValueChange).not.toHaveBeenCalled();gate.dispose();
  });
  it('the real options component filters to its quiet empty face, focuses real options and chooses without inventing a result',()=>{
    const copy = boardBoundary('worst','en').copy, onValueChange = vi.fn(), props = {id:'options',label:copy.displayName,value:null,onValueChange,options:[{value:'a',label:'Alpha'},{value:'off',label:'Unavailable',disabled:true},{value:'b',label:'Beta'}],messages:copy.select,searchable:true,engagement:{open:true,focus:true,input:'keyboard' as const,edge:'first' as const}};
    const draw = ()=>render(()=>SelectOptions(props));let view = draw();const input = elements(view).find(node=>node.type === Input)!;
    (input.props.onValueChange as (value:string)=>void)('no match');view = draw();const empty = elements(view).find(node=>node.type === State)!;expect(empty.props.title).toBe(copy.select.emptyTitle);expect(empty.props.kind).toBeUndefined();expect(elements(view).some(node=>node.props.role === 'option')).toBe(false);
    (elements(view).find(node=>node.type === Input)!.props.onValueChange as (value:string)=>void)('Beta');view = draw();const option = elements(view).find(node=>node.props.role === 'option')!;click(option);expect(onValueChange).toHaveBeenCalledExactlyOnceWith('b');expect(elements(draw()).find(node=>node.type === Popover)?.props.open).toBe(false);
  });
  it('real options focus/roving paths skip disabled choices and follow RTL rather than just listing those state names',()=>{
    hooks.dir = 'rtl';const copy = boardBoundary('worst','ar').copy, props = {id:'options',label:copy.displayName,value:null,onValueChange:vi.fn(),options:[{value:'a',label:'Alpha'},{value:'off',label:'Unavailable',disabled:true},{value:'b',label:'Beta'}],messages:copy.select,engagement:{open:true,focus:true,input:'keyboard' as const,edge:'first' as const}};
    const view = render(()=>SelectOptions(props)), nodes = Array.from({length:3},()=>({focus:vi.fn(),scrollIntoView:vi.fn()}));const list = elements(view).find(node=>node.props.role === 'listbox')!;
    (list.props.ref as {current:unknown}).current = {querySelectorAll:()=>nodes};const content = elements(view).find(node=>node.type === PopoverContent)!;(content.props.onOpenAutoFocus as (event:unknown)=>void)({preventDefault:vi.fn()});expect(nodes[0].focus).toHaveBeenCalledOnce();
    const option = elements(view).find(node=>node.props.role === 'option')!;(option.props.onKeyDown as (event:unknown)=>void)({key:'ArrowRight',preventDefault:vi.fn()});expect(nodes[2].focus).toHaveBeenCalledOnce();expect(nodes[1].focus).not.toHaveBeenCalled();
  });
  it('all toast kinds and actual loading/completion/repeat actions receive their usual or worst payloads',()=>{
    vi.useFakeTimers();for (const mode of ['demo','worst'] as const) {
      hooks.slots = [];const copy = boardBoundary(mode,'ar').copy, draw = ()=>render(()=>ToastCase({copy,locale:'ar',initialCount:boardBoundary(mode,'ar').count}));
      for (const label of [copy.toastInfo,copy.toastSuccess,copy.toastWarning,copy.toastError]) click(button(draw(),label));
      for (const kind of ['info','success','warning','error']) {const entry = currentToasts().find(item=>item.kind === kind)!;expect(entry.description).toBe(copy.toastBody);expect(entry.action?.label).toBe(copy.toastAction);}
      click(button(draw(),copy.toastLoading));const pending = currentToasts().find(entry=>entry.kind === 'loading')!;expect(pending.title).toBe(copy.toastLoading);click(button(draw(),copy.finishLoading));expect(currentToasts().find(entry=>entry.id === pending.id)?.kind).toBe('success');
      const repeat = button(draw(),copy.repeatNotice);click(repeat);click(repeat);expect(currentToasts().filter(entry=>!entry.action && entry.kind === 'error' && entry.title === copy.toastError)).toHaveLength(1);clearToasts();
    }
  });
  it('the real wide-dialog reopen path uses the exit token and never overwrites a newer surface choice',()=>{
    vi.useFakeTimers();const sample = boardBoundary('worst','en'), draw = ()=>render(()=>SurfaceCases({mode:'worst',locale:'en',copy:sample.copy,initialSurface:'wide'}));
    const modal = elements(draw()).filter(node=>node.type === Dialog), wide = modal.find(node=>node.props.open === true)!;expect(wide).toBeDefined();const body = elements(wide).find(node=>typeof node.props.reopen === 'function')!;(body.props.reopen as (event:unknown)=>void)({detail:1,currentTarget:{}});expect(elements(draw()).filter(node=>node.type === Dialog).every(node=>node.props.open === false)).toBe(true);vi.advanceTimersByTime(59);expect(elements(draw()).filter(node=>node.type === Dialog).every(node=>node.props.open === false)).toBe(true);vi.advanceTimersByTime(1);expect(elements(draw()).filter(node=>node.type === Dialog)[1].props.open).toBe(true);
    const again = elements(elements(draw()).filter(node=>node.type === Dialog)[1]).find(node=>typeof node.props.reopen === 'function')!;(again.props.reopen as (event:unknown)=>void)({detail:1,currentTarget:{}});(elements(draw()).filter(node=>node.type === Dialog)[0].props.onOpenChange as (open:boolean)=>void)(true);vi.runAllTimers();expect(elements(draw()).filter(node=>node.type === Dialog).map(node=>node.props.open)).toEqual([true,false]);
  });
});
