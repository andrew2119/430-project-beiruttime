import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api/client';
import { copy } from './copy';
import { blank } from './form';

const memory = vi.hoisted(() => ({ values: [] as unknown[], refs: [] as {current: unknown}[], state: 0, ref: 0, locale: 'en' as 'en' | 'ar' }));
vi.mock('react', async importOriginal => ({
  ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = memory.state++;
    if (!(index in memory.values)) memory.values[index] = initial;
    return [memory.values[index], (value: unknown) => { memory.values[index] = value; }];
  },
  useRef: (initial: unknown) => {
    const index = memory.ref++;
    return memory.refs[index] ??= {current: initial};
  },
  useEffect: () => {},
}));
vi.mock('@/features/identity/session', () => ({ useSession: vi.fn(), useSessionState: vi.fn(), refreshSession: vi.fn() }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => memory.locale }));
vi.mock('next/navigation', () => ({ useRouter: vi.fn() }));
vi.mock('@/shell/page-header', () => ({ PageLayout: vi.fn(), PageHeader: vi.fn() }));
vi.mock('./client', () => ({ lookup: vi.fn(), send: vi.fn() }));
vi.mock('@beirut-time/ui', () => ({
  Card: ({children}: {children: ReactNode}) => createElement('section', null, children),
  State: ({body, children}: {body: string; children?: ReactNode}) => createElement('div', null, body, children),
  ButtonLink: ({href, children}: {href: string; children: ReactNode}) => createElement('a', {href}, children),
  BidiReference: ({children}: {children: ReactNode}) => createElement('span', null, children),
  Input: (props: object) => createElement('input', props),
  Label: ({children}: {children: ReactNode}) => createElement('label', null, children),
  Select: () => null, Button: () => null,
}));
import { LifecycleForm } from './view';
import { lookup, send } from './client';
import { commandFor } from './form';

function render() {
  memory.state = 0; memory.ref = 0;
  return LifecycleForm({actor: id, organization: null});
}
const id = '00000000-0000-4000-8000-000000000001';

describe.each(['en', 'ar'] as const)('revoked private access in %s', locale => {
  it.each([401, 403])('clears a pending view after %s without replacing the operation', async status => {
    vi.clearAllMocks();
    memory.values = []; memory.refs = []; memory.locale = locale;
    let tree = render();
    const fields = {listing: id, watch: id, revision: '1', proof: 'synthetic-private-proof', quote: 'synthetic-quote', quoteRevision: '1', policy: 'synthetic-policy'};
    // Populate the mounted form, then submit and receive a pending receipt.
    memory.values[1] = fields;
    const command = commandFor(fields, 'pause', id, null, id);
    const pending = {...command, state: 'pending', responsible_operator_id: 'synthetic-private-operator', next_review_at: '2026-11-18T12:00:00Z', escalate_at: '2026-11-19T12:00:00Z'};
    vi.mocked(send).mockResolvedValueOnce(pending as Awaited<ReturnType<typeof send>>);
    vi.stubGlobal('crypto', {randomUUID: vi.fn(() => id)});
    tree = render();
    const submit = tree.props.children.props.onSubmit;
    submit({preventDefault: vi.fn()});
    await vi.waitFor(() => expect(memory.values[5]).toBe(false));
    tree = render();
    expect(renderToStaticMarkup(tree)).toContain('synthetic-private-operator');
    vi.mocked(lookup).mockRejectedValueOnce(new ApiError(status, 'access_denied', 'synthetic-request'));
    const retry = tree.props.children.props.onSubmit;
    retry({preventDefault: vi.fn()});
    await vi.waitFor(() => expect(memory.values[0]).toBe(true));
    const html = renderToStaticMarkup(render());
    expect(html).toContain(copy[locale].accessDenied);
    expect(html).toContain(`href="/${locale}/account"`);
    for (const privateValue of [id, fields.proof, pending.responsible_operator_id, pending.next_review_at]) expect(html).not.toContain(privateValue);
    expect(html).not.toContain('<form');
    expect(memory.values[1]).toEqual(blank);
    expect(memory.values[3]).toBeNull();
    expect(memory.values[6]).toBeNull();
    retry({preventDefault: vi.fn()});
    expect(lookup).toHaveBeenCalledExactlyOnceWith(command);
    expect(send).toHaveBeenCalledExactlyOnceWith(command);
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});
