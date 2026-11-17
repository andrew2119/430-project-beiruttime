import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { LocaleContext } from '../../../../web/shell/locale-context';
import { MessagePhotoView } from '../../../../web/features/message-photos/view';
import type { MessagePhotos, PhotoResult } from '../../../../packages/contracts-comms/message-photos';

// Minimal host document for real mounted state/effects; geometry is checked separately.
class HostNode {
  nodeType = 1; nodeName: string; tagName: string; namespaceURI = 'http://www.w3.org/1999/xhtml';
  parentNode: HostNode | null = null; childNodes: HostNode[] = []; style = {}; attributes: Record<string, string> = {};
  ownerDocument: HostDocument; value = ''; checked = false; disabled = false; textContent = '';
  constructor(name: string, doc: HostDocument) { this.nodeName = this.tagName = name.toUpperCase(); this.ownerDocument = doc; }
  appendChild(node: HostNode) { node.parentNode?.removeChild(node); this.childNodes.push(node); node.parentNode = this; return node; }
  removeChild(node: HostNode) { this.childNodes.splice(this.childNodes.indexOf(node), 1); node.parentNode = null; return node; }
  insertBefore(node: HostNode, before: HostNode) { node.parentNode?.removeChild(node); this.childNodes.splice(this.childNodes.indexOf(before), 0, node); node.parentNode = this; return node; }
  setAttribute(name: string, value: string) { this.attributes[name] = String(value); }
  removeAttribute(name: string) { delete this.attributes[name]; }
  addEventListener() {} removeEventListener() {}
  get firstChild() { return this.childNodes[0] ?? null; }
  get lastChild(): HostNode | null { return this.childNodes.at(-1) ?? null; }
}
class HostDocument {
  nodeType = 9; activeElement = null;
  createElement(name: string) { return new HostNode(name, this); }
  createElementNS(_ns: string, name: string) { return this.createElement(name); }
  createTextNode(text: string) { const n = this.createElement('#text'); n.nodeType = 3; n.textContent = text; return n; }
  addEventListener() {} removeEventListener() {}
}
function props(node: HostNode): Record<string, unknown> { return (node as unknown as Record<string, Record<string, unknown>>)[Object.keys(node).find(key => key.startsWith('__reactProps$'))!]!; }
function all(node: HostNode): HostNode[] { return [node, ...node.childNodes.flatMap(all)]; }
const scope = { actor: 'buyer', business: 'business', thread: 'thread', watch: 'watch', revision: 1 };
const receipt = (operation_id: string, state: PhotoResult['state']): PhotoResult => ({ schema_version: 'communications.message-photos.v1', operation_id, subject_id: 'thread', watch_id: 'watch', actor_id: 'buyer', organization_id: 'business', expected_revision: 1, revision: 1, state, photo: 'photo', pending_reason: null, next_actor: null, next_review_at: null });
afterEach(() => { vi.unstubAllGlobals(); });
it('retains the mounted file, declaration, page and pending references across both languages; recovers denial only after a current read', async () => {
  const doc = new HostDocument();
  vi.stubGlobal('document', doc);
  vi.stubGlobal('self', globalThis);
  vi.stubGlobal('window', { document: doc, setTimeout, clearTimeout, event: undefined, HTMLIFrameElement: class {} });
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = doc.createElement('div');
  const root = createRoot(container as unknown as HTMLElement);
  const upload = vi.fn(async (_file: File, operation: string) => receipt(operation, 'uploaded'));
  const attach = vi.fn(async (_photo: string, operation: string) => { throw Object.assign(new Error(operation), { code: 'unavailable' }); });
  const list = vi.fn(async (offset: number) => ({ items: [], total: 1000, next_offset: offset + 20 }));
  const provider: MessagePhotos = { upload, attach, list, operation: async operation => receipt(operation, 'pending'), bytes: async () => new Blob() };
  const render = async (locale: 'en' | 'ar') => { await act(async () => root.render(<LocaleContext.Provider value={locale}><MessagePhotoView scope={scope} accessFingerprint="current" provider={provider}/></LocaleContext.Provider>)); };
  const input = () => all(container).find(n => props(n)?.type === 'file')!;
  const checkbox = () => all(container).find(n => props(n)?.type === 'checkbox')!;
  const click = async (label: string) => { const node = all(container).find(n => n.tagName === 'BUTTON' && all(n).some(child => child.textContent === label))!; await act(async () => { (props(node).onClick as () => void)(); }); };
  try {
    await render('en');
    const original = input(), file = { name: 'تفصيل-detail-⌚.jpg', type: 'image/jpeg', size: 100 } as File;
    await act(async () => { (props(original).onChange as (e: unknown) => void)({ target: { files: [file] } }); (props(checkbox()).onChange as (e: unknown) => void)({ currentTarget: { checked: true } }); });
    await click('More photos');
    await render('ar');
    expect(input()).toBe(original); expect(props(checkbox()).checked).toBe(true);
    expect(list.mock.calls.map((c: [number]) => c[0])).toEqual([0, 20]); expect(upload).not.toHaveBeenCalled();
    await click('مشاركة الصورة');
    const reference = attach.mock.calls[0][1];
    await render('en'); await render('ar');
    expect(input()).toBe(original); expect(props(checkbox()).checked).toBe(true);
    expect(attach).toHaveBeenCalledTimes(1);
    await click('إعادة المحاولة بالإجراء نفسه');
    expect(upload).toHaveBeenCalledTimes(1); expect(upload.mock.calls[0][0]).toBe(file);
    expect(attach.mock.calls[1][1]).toBe(reference);
    let finishList!: (page: { items: never[]; total: number; next_offset: number }) => void;
    list.mockImplementationOnce(() => new Promise(resolve => { finishList = resolve; }));
    await click('المزيد من الصور');
    attach.mockImplementation(async () => { throw { code: 'denied' }; });
    await click('إعادة المحاولة بالإجراء نفسه');
    await act(async () => finishList({ items: [], total: 1000, next_offset: 60 }));
    expect(props(input()).disabled).toBe(true);
    expect(all(container).some(n => n.tagName === 'A' && props(n).href === '/ar/inbox')).toBe(true);
    list.mockRejectedValueOnce({ code: 'denied' });
    await click('التحقق من الوصول وبدء مسودة جديدة');
    expect(props(input()).disabled).toBe(true);
    await click('التحقق من الوصول وبدء مسودة جديدة');
    expect(list.mock.calls.at(-1)?.[0]).toBe(40);
    expect(props(input()).disabled).toBe(false); expect(props(checkbox()).checked).toBe(false);
    expect(all(container).some(n => n.tagName === 'A' && props(n).href === '/ar/inbox')).toBe(false);
    expect(attach).toHaveBeenCalledTimes(3);
  } finally { await act(async () => root.unmount()); }
});

it.each(['en', 'ar'] as const)('discards delayed private bytes after a concurrent access denial in %s', async (locale: 'en' | 'ar') => {
  const doc = new HostDocument();
  vi.stubGlobal('document', doc);
  vi.stubGlobal('self', globalThis);
  vi.stubGlobal('window', { document: doc, setTimeout, clearTimeout, event: undefined, HTMLIFrameElement: class {} });
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const decode = vi.fn();
  vi.stubGlobal('createImageBitmap', decode);
  const container = doc.createElement('div');
  const root = createRoot(container as unknown as HTMLElement);
  let denyList!: (error: unknown) => void;
  let finishBytes!: (bytes: Blob) => void;
  let bytesSignal!: AbortSignal;
  const page = { items: [{ id: 'photo', width: 40, height: 30 }], total: 2, next_offset: 20 };
  const list = vi.fn<MessagePhotos['list']>().mockResolvedValue(page);
  const provider: MessagePhotos = {
    list,
    bytes: (_photo, signal) => { bytesSignal = signal; return new Promise(resolve => { finishBytes = resolve; }); },
    upload: async (_file, operation) => receipt(operation, 'uploaded'),
    attach: async (_photo, operation) => receipt(operation, 'attached'),
    operation: async operation => receipt(operation, 'pending'),
  };
  const click = async (label: string) => {
    const node = all(container).find(n => n.tagName === 'BUTTON' && all(n).some(child => child.textContent === label))!;
    await act(async () => { (props(node).onClick as () => void)(); });
  };
  const labels = locale === 'en'
    ? { next: 'More photos', view: 'View photo', recover: 'Check access and start a new draft', support: '/en/inbox' }
    : { next: 'المزيد من الصور', view: 'عرض الصورة', recover: 'التحقق من الوصول وبدء مسودة جديدة', support: '/ar/inbox' };
  const input = () => all(container).find(n => props(n)?.type === 'file')!;
  try {
    await act(async () => root.render(<LocaleContext.Provider value={locale}><MessagePhotoView scope={scope} accessFingerprint="current" provider={provider}/></LocaleContext.Provider>));
    list.mockImplementationOnce(() => new Promise((_resolve, reject) => { denyList = reject; }));
    await click(labels.next);
    await click(labels.view);
    await act(async () => denyList({ code: 'denied' }));
    expect(bytesSignal.aborted).toBe(true);
    expect(props(input()).disabled).toBe(true);
    expect(all(container).some(n => n.tagName === 'A' && props(n).href === labels.support)).toBe(true);
    await act(async () => finishBytes(new Blob(['private pixels'])));
    expect(decode).not.toHaveBeenCalled();
    expect(all(container).some(n => n.tagName === 'CANVAS')).toBe(false);
    expect(props(input()).disabled).toBe(true);
    expect(all(container).some(n => n.tagName === 'A' && props(n).href === labels.support)).toBe(true);
    await click(labels.recover);
    expect(props(input()).disabled).toBe(false);
    expect(decode).not.toHaveBeenCalled();
  } finally { await act(async () => root.unmount()); }
});

it.each(['en', 'ar'] as const)('recovers conclusive rejections without replaying rejected operations in %s', async (locale: 'en' | 'ar') => {
  const doc = new HostDocument();
  vi.stubGlobal('document', doc);
  vi.stubGlobal('self', globalThis);
  vi.stubGlobal('window', { document: doc, setTimeout, clearTimeout, event: undefined, HTMLIFrameElement: class {} });
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = doc.createElement('div');
  const root = createRoot(container as unknown as HTMLElement);
  const { copy } = await import('../../../../web/features/message-photos/copy');
  const t = copy[locale];
  const upload = vi.fn<MessagePhotos['upload']>().mockRejectedValue({ code: 'photo_limit' });
  const list = vi.fn<MessagePhotos['list']>().mockResolvedValue({ items: [], total: 8, next_offset: null });
  const provider: MessagePhotos = { upload, list, attach: async (_photo, operation) => receipt(operation, 'attached'), operation: async operation => receipt(operation, 'pending'), bytes: async () => new Blob() };
  const input = () => all(container).find(n => props(n)?.type === 'file')!;
  const button = (label: string) => all(container).find(n => n.tagName === 'BUTTON' && all(n).some(child => child.textContent === label))!;
  const click = async (label: string) => { await act(async () => { (props(button(label)).onClick as () => void)(); }); };
  const choose = async () => { await act(async () => {
    (props(input()).onChange as (e: unknown) => void)({ target: { files: [{ name: 'detail.jpg', type: 'image/jpeg', size: 100 }] } });
    const checkbox = all(container).find(n => props(n)?.type === 'checkbox')!;
    (props(checkbox).onChange as (e: unknown) => void)({ currentTarget: { checked: true } });
  }); };
  const render = async (revision = 1) => { await act(async () => root.render(<LocaleContext.Provider value={locale}><MessagePhotoView scope={{ ...scope, revision }} accessFingerprint="current" provider={provider}/></LocaleContext.Provider>)); };
  try {
    await render(); await choose(); await click(t.send);
    const rejectedReference = upload.mock.calls[0][1];
    expect(props(input()).disabled).toBe(true);
    expect(props(button(t.retry)).disabled).toBe(true);
    list.mockRejectedValueOnce({ code: 'unavailable' });
    await click(t.recheck);
    expect(props(input()).disabled).toBe(true);
    expect(upload).toHaveBeenCalledTimes(1);
    await click(t.recheck);
    expect(props(input()).disabled).toBe(false);
    expect(props(all(container).find(n => props(n)?.type === 'checkbox')!).checked).toBe(false);
    upload.mockRejectedValueOnce({ code: 'stale_revision' });
    await choose(); await click(t.send);
    expect(upload.mock.calls[1][1]).not.toBe(rejectedReference);
    expect(all(container).some(n => n.tagName === 'A' && props(n).href === `/${locale}/inbox` && all(n).some(child => child.textContent === t.review))).toBe(true);
    expect(props(button(t.retry)).disabled).toBe(true);
    // Even an invoked disabled command cannot replay a conclusively rejected draft.
    await click(t.retry);
    expect(upload).toHaveBeenCalledTimes(2);
    await render(2);
    expect(props(input()).disabled).toBe(false);
    expect(props(all(container).find(n => props(n)?.type === 'checkbox')!).checked).toBe(false);
  } finally { await act(async () => root.unmount()); }
});
