import { act, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import fixtures from '../../../../packages/contracts-catalog/comparison/fixtures.json';
import type { Comparison, CompareRequest } from '../../../../packages/contracts-catalog/comparison';
import type { PageRead } from '../../../../web/lib/page-speed/definition';
import { LocaleContext } from '../../../../web/shell/locale-context';
import { messages } from '../../../../web/features/comparison/messages';

const pending = vi.hoisted(() => ({ reads: [] as PageRead<unknown>[], revision: 1, refetch: vi.fn(), input: undefined as undefined | ((value: string) => void) }));
vi.mock('../../../../web/lib/page-speed/read', () => ({
  usePageRead: (read: PageRead<unknown> | null) => {
    if (read) pending.reads.push(read);
    if (!read) return { isFetching: false, isError: false, data: undefined, refetch: pending.refetch };
    const body = JSON.parse(String(read.key[2])) as CompareRequest;
    const selected = body.selections[0];
    const stale = selected.expected_revision !== null && selected.expected_revision !== pending.revision;
    const data: Comparison = { ...fixtures.success, schema_version: 'comparison.v1', operation_id: String(read.key[1]), columns: [{
      ...selected, state: stale ? 'stale' : 'available', revision: pending.revision,
      facts: stale ? null : { ...fixtures.success.columns[0].facts, title: { en: `Revision ${pending.revision}`, ar: `نسخة ${pending.revision}` } } as Comparison['columns'][number]['facts'],
    }] };
    return { isFetching: false, isError: false, data, refetch: pending.refetch };
  },
}));
vi.mock('@beirut-time/ui/foundation', () => ({
  Input: ({ value, label, onValueChange }: { value: string; label: string; onValueChange: (value: string) => void }) => {
    pending.input = onValueChange;
    return <label>{label}<input value={value} readOnly/></label>;
  },
  Button: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => <button onClick={onClick}>{children}</button>,
  State: ({ title, body, children }: { title: string; body: string; children?: ReactNode }) => <section>{title}{body}{children}</section>,
  Skeleton: () => <span/>, formatAmount: vi.fn(), formatNumber: vi.fn(),
}));
vi.mock('../../../../web/shell/foundation/page', () => ({
  PageFrame: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PageBody: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PageHeader: ({ title, tools }: { title: string; tools: ReactNode }) => <header>{title}{tools}</header>,
}));
import ComparisonView from '../../../../web/features/comparison/view';

// Minimal host nodes keep this lifecycle check independent of a browser process.
class HostNode {
  nodeType = 1;
  tagName: string;
  namespaceURI = 'http://www.w3.org/1999/xhtml';
  children: HostNode[] = [];
  parentNode: HostNode | null = null;
  style = {};
  attributes: Record<string, string> = {};
  value = '';
  private content = '';
  constructor(public nodeName: string, public ownerDocument: Document) { this.tagName = nodeName.toUpperCase(); }
  appendChild(node: HostNode) { this.children.push(node); node.parentNode = this; return node; }
  removeChild(node: HostNode) { this.children.splice(this.children.indexOf(node), 1); node.parentNode = null; return node; }
  insertBefore(node: HostNode, before: HostNode) { this.children.splice(this.children.indexOf(before), 0, node); node.parentNode = this; return node; }
  setAttribute(key: string, value: string) { this.attributes[key] = value; }
  removeAttribute(key: string) { delete this.attributes[key]; }
  addEventListener() {}
  removeEventListener() {}
  set textContent(value: string) { this.content = value; this.children = []; }
  set nodeValue(value: string) { this.content = value; }
  get nodeValue(): string { return this.content; }
  get textContent(): string { return this.content + this.children.map(child => child.textContent).join(''); }
}



it('pins a successful selection, retries stale facts and requires explicit review', async () => {
  const document = { nodeType: 9, addEventListener() {}, removeEventListener() {},
    createElement: (name: string) => new HostNode(name, document as unknown as Document),
    createTextNode: (text: string) => { const node = new HostNode('#text', document as unknown as Document); node.nodeType = 3; node.textContent = text; return node; },
  };
  vi.stubGlobal('window', { event: undefined, HTMLIFrameElement: class {} });
  vi.stubGlobal('document', document);
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container as unknown as Element);
  const screen = (locale: 'en' | 'ar') => <LocaleContext.Provider value={locale}><ComparisonView/></LocaleContext.Provider>;
  const find = (name: string, node = container): HostNode | undefined => node.nodeName === name ? node : node.children.map(child => find(name, child)).find(Boolean);
  const submit = () => {
    const form = find('form')!;
    const propsKey = Object.keys(form).find(key => key.startsWith('__reactProps$'))!;
    (form as unknown as Record<string, { onSubmit: (event: { preventDefault: () => void }) => void }>)[propsKey].onSubmit({ preventDefault() {} });
  };
  try {
    await act(async () => root.render(screen('en')));
    await act(async () => pending.input!('demo-13'));
    await act(async () => submit());
    const key = pending.reads.at(-1)!.key;
    expect(JSON.parse(String(key[2])).selections[0].expected_revision).toBe(1);
    expect(container.textContent).toContain('Revision 1');
    const click = (label: string, node = container): boolean => {
      if (node.nodeName === 'button' && node.textContent === label) {
        const propsKey = Object.keys(node).find(key => key.startsWith('__reactProps$'))!;
        (node as unknown as Record<string, { onClick: () => void }>)[propsKey].onClick();
        return true;
      }
      return node.children.some(child => click(label, child));
    };
    pending.revision = 2;
    await act(async () => { expect(click(messages.en.retry)).toBe(true); root.render(screen('en')); });
    expect(pending.refetch).toHaveBeenCalledTimes(1);
    expect(pending.reads.at(-1)!.key).toEqual(key);
    expect(container.textContent).toContain(messages.en.stale);
    expect(container.textContent).not.toContain('Revision 2');
    await act(async () => { expect(click(messages.en.retry)).toBe(true); root.render(screen('ar')); });
    expect(pending.reads.at(-1)!.key).toEqual(key);
    expect(container.textContent).toContain(messages.ar.stale);
    await act(async () => { expect(click(messages.ar.review)).toBe(true); });
    expect(container.textContent).toContain('نسخة 2');
    const reviewedKey = pending.reads.at(-1)!.key;
    expect(reviewedKey[1]).not.toBe(key[1]);
    expect(JSON.parse(String(reviewedKey[2])).selections[0].expected_revision).toBe(2);
    await act(async () => { expect(click(messages.ar.retry)).toBe(true); root.render(screen('en')); });
    expect(pending.reads.at(-1)!.key).toEqual(reviewedKey);
  } finally {
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  }
});
