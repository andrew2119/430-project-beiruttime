import { act, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { PageRead } from '../../../../web/lib/page-speed/definition';
import { LocaleContext } from '../../../../web/shell/locale-context';
import { messages } from '../../../../web/features/comparison/messages';

const pending = vi.hoisted(() => ({ reads: [] as PageRead<unknown>[], refetch: vi.fn(), input: undefined as undefined | ((value: string) => void) }));
vi.mock('../../../../web/lib/page-speed/read', () => ({
  usePageRead: (read: PageRead<unknown> | null) => {
    if (read) pending.reads.push(read);
    return { isFetching: Boolean(read), isError: false, data: undefined, refetch: pending.refetch };
  },
}));
vi.mock('@beirut-time/ui/foundation', () => ({
  Input: ({ value, label, onValueChange }: { value: string; label: string; onValueChange: (value: string) => void }) => {
    pending.input = onValueChange;
    return <label>{label}<input value={value} readOnly/></label>;
  },
  Button: ({ children }: { children: ReactNode }) => <button>{children}</button>,
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



it('keeps the mounted draft, selections and pending request through both language changes', async () => {
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
    await act(async () => pending.input!('unsent-العربية-⌚'));
    const input = find('input')!;
    const originalKey = pending.reads.at(-1)!.key;
    expect(JSON.parse(String(originalKey[2])).selections).toEqual([{ watch_id: 'demo-13', expected_revision: null }]);
    expect(originalKey[1]).toEqual(expect.any(String));
    expect(originalKey[1]).not.toBe('');
    const readCount = pending.reads.length;
    for (const locale of ['ar', 'en'] as const) {
      await act(async () => root.render(screen(locale)));
      expect(find('input')).toBe(input);
      expect(input.value).toBe('unsent-العربية-⌚');
      expect(container.textContent).toContain(messages[locale].title);
      expect(container.textContent).toContain(messages[locale].loading);
      expect(container.textContent).toContain('demo-13');
      expect(container.textContent).toContain(String(originalKey[1]));
      expect(pending.reads.at(-1)!.key).toEqual(originalKey);
    }
    expect(pending.reads).toHaveLength(readCount + 2);
    expect(pending.refetch).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
  }
});
