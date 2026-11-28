import type { ReactElement, ReactNode } from 'react';
import { expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({
  query: { data: { revision: 1, email: 'old@example.invalid', pending_challenge: { id: 'test-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending' } } as Record<string, unknown> | undefined, isError: false, isPending: false, error: null as Error | null },
  slots: [] as unknown[], index: 0, running: Promise.resolve(), request: vi.fn(), refetch: vi.fn(),
}));
vi.mock('react', async original => ({
  ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const index = state.index++;
    if (!(index in state.slots)) state.slots[index] = initial;
    return [state.slots[index], (value: unknown) => { state.slots[index] = value; }];
  },
  useRef: (initial: unknown) => {
    const index = state.index++;
    if (!(index in state.slots)) state.slots[index] = { current: initial };
    return state.slots[index];
  },
}));
vi.mock('./reads', () => ({ contactsRead: vi.fn(), useBusinessRead: () => ({
  ...state.query, refetch: state.refetch,
}) }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: 'test-access' }) }));
vi.mock('./transport', () => ({ businessRequest: state.request }));
vi.mock('./components', () => ({
  Workspace: 'section', Field: 'input', Select: 'select', Submit: 'button', Feedback: 'output', BusinessLoading: 'output',
  text: (data: FormData, name: string) => String(data.get(name) ?? ''),
  useCopy: () => ({ retry: 'Retry', verify: 'Verify', operationHelp: 'Keep reference', showCode: 'Show sample code', actionReference: 'Action reference', recoverAction: 'Recover result' }),
  useAction: () => ({ pending: false, run: (invoke: () => Promise<void>) => {
    state.running = invoke().catch(() => {}); return state.running;
  } }),
}));
import ContactDetails from './contacts';
function elements(node: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object' || !('props' in node)) return [];
  const element = node as ReactElement<Record<string, unknown>>;
  return [element, ...elements(element.props.children as ReactNode)];
}
it.each(['no challenge', 'failed refresh', 'denied refresh'])('retains the original verification through %s after a lost response', async refresh => {
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 1, email: 'old@example.invalid', pending_challenge: { id: 'test-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending' } };
  state.request.mockReset(); state.refetch.mockReset();
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData { constructor() { super(); this.set('code', '123456'); } });
  try {
    state.request.mockRejectedValueOnce(new TypeError('Response unavailable')).mockResolvedValue({ revision: 2 });
    const render = () => { state.index = 0; return elements(ContactDetails()); };
    const submit = (nodes: ReturnType<typeof render>) => {
      const forms = nodes.filter(node => node.type === 'form');
      (forms[1].props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    };
    submit(render()); await state.running;
    expect(state.refetch).not.toHaveBeenCalled();
    if (refresh === 'no challenge') state.query.data = { revision: 2, email: 'new@example.invalid', pending_challenge: null };
    else { state.query.data = undefined; state.query.isError = true; state.query.error = new Error('Unavailable'); }
    if (refresh === 'denied refresh') {
      const { ApiError } = await import('@/lib/api/client');
      state.query.error = new ApiError(403, 'denied', '');
    }
    const pending = render();
    expect(pending.filter(node => node.type === 'form')).toHaveLength(refresh === 'denied refresh' ? 1 : 2);
    expect(pending.some(node => node.type === 'input' && node.props.name === 'reauth')).toBe(true);
    expect(pending.some(node => node.type === 'fieldset' && node.props.disabled && elements(node.props.children as ReactNode).some(field => field.props.name === 'code'))).toBe(refresh !== 'denied refresh');
    if (refresh === 'denied refresh') {
      expect(pending.some(node => node.props.children === 'old@example.invalid')).toBe(false);
      expect(pending.some(node => node.type === 'input' && node.props.name === 'code')).toBe(false);
      expect(state.request).toHaveBeenCalledTimes(1);
      state.query.isError = false; state.query.error = null;
      state.query.data = { revision: 2, pending_challenge: null };
    }
    submit(render()); await state.running;
    expect(state.request.mock.calls[1]).toEqual(state.request.mock.calls[0]);
    expect(state.request.mock.calls[0][1].headers['Idempotency-Key']).toBeTruthy();
    expect(state.refetch).toHaveBeenCalledTimes(1);
    expect(render().filter(node => node.type === 'form')).toHaveLength(1);
  } finally { vi.unstubAllGlobals(); }
});

it('keeps a resumed challenge and entered fields mounted through a failed refresh before submission', () => {
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 1, pending_challenge: { id: 'test-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending' } };
  const render = () => { state.index = 0; return elements(ContactDetails()); };
  const original = render().filter(node => node.type === 'form');
  expect(original).toHaveLength(2);
  state.query.data = undefined; state.query.isError = true; state.query.error = new Error('Unavailable');
  const retained = render();
  expect(retained.filter(node => node.type === 'form').map(node => node.type)).toEqual(original.map(node => node.type));
  expect(retained.some(node => node.type === 'input' && node.props.name === 'code')).toBe(true);
  expect(retained.some(node => node.type === 'input' && node.props.name === 'reauth')).toBe(true);
});


it.each([401, 403])('clears retained recipients after authorization denial %i', async status => {
  const { ApiError } = await import('@/lib/api/client');
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 1, email: 'old@example.invalid', email_verified: true };
  const render = () => { state.index = 0; return elements(ContactDetails()); };
  expect(render().some(node => node.props.children === 'old@example.invalid')).toBe(true);
  state.query.isError = true; state.query.error = new ApiError(status, 'denied', '');
  expect(render().some(node => node.props.children === 'old@example.invalid')).toBe(false);
  state.query.data = undefined; state.query.error = new TypeError('Unavailable');
  expect(render().some(node => node.props.children === 'old@example.invalid')).toBe(false);
});

it.each([401, 403])('hides a retained challenge and revealed code on denial %i while preserving authorized recovery', async status => {
  const { ApiError } = await import('@/lib/api/client');
  state.slots = []; state.query.isError = false; state.query.error = null;
  const expiresAt = '2026-11-17T12:00:00Z';
  state.query.data = { revision: 1, email: 'old@example.invalid', pending_challenge: {
    id: 'test-challenge', expires_at: expiresAt, delivery_mode: 'sample_simulator',
  } };
  state.request.mockReset(); state.refetch.mockReset();
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData { constructor() { super(); this.set('code', '654321'); } });
  try {
    state.request.mockResolvedValueOnce({ code: '654321' })
      .mockRejectedValueOnce(new TypeError('Response unavailable')).mockResolvedValue({ revision: 2 });
    const render = () => { state.index = 0; return elements(ContactDetails()); };
    const submit = (nodes: ReturnType<typeof render>) => {
      const form = nodes.filter(node => node.type === 'form')[1];
      (form.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    };
    (render().find(node => node.props.children === 'Show sample code')!.props.onClick as () => void)();
    await state.running;
    const revealed = render();
    expect(revealed.some(node => node.props.children === '654321')).toBe(true);
    expect(revealed.some(node => node.props.dateTime === expiresAt)).toBe(true);
    submit(revealed); await state.running;
    const original = state.request.mock.calls[1];
    const reference = original[1].headers['Idempotency-Key'];
    expect(reference).toBeTruthy();
    expect(render().some(node => node.props.children === reference)).toBe(true);
    const error = new ApiError(status, 'denied', '');
    state.query.isError = true; state.query.error = error;
    const assertPrivateDetailsHidden = () => {
      const nodes = render();
      expect(nodes.some(node => node.props.children === 'old@example.invalid')).toBe(false);
      expect(nodes.some(node => node.props.dateTime === expiresAt)).toBe(false);
      expect(nodes.some(node => node.props.children === '654321')).toBe(false);
      expect(nodes.some(node => node.props.children === 'Show sample code')).toBe(false);
      expect(nodes.some(node => node.type === 'input' && node.props.name === 'code')).toBe(false);
      expect(nodes.filter(node => node.type === 'form')).toHaveLength(1);
      expect(state.request).toHaveBeenCalledTimes(2);
    };
    assertPrivateDetailsHidden();
    expect(render().some(node => node.props.error === error)).toBe(true);
    state.query.data = undefined; state.query.error = new TypeError('Unavailable');
    assertPrivateDetailsHidden();
    state.query.isError = false; state.query.error = null;
    state.query.data = { revision: 2, pending_challenge: {
      id: 'replacement-challenge', expires_at: '2026-11-17T13:00:00Z', delivery_mode: 'delivery_pending',
    } };
    const authorized = render();
    expect(authorized.some(node => node.props.children === reference)).toBe(true);
    submit(authorized); await state.running;
    expect(state.request.mock.calls[2]).toEqual(original);
    expect(original[0]).toBe('/v1/contacts/challenges/test-challenge/verify');
    expect(original[1].body).toBe(JSON.stringify({ code: '654321' }));
    expect(state.refetch).toHaveBeenCalledTimes(1);
    expect(render().some(node => node.props.children === '654321')).toBe(false);
    expect(render().filter(node => node.type === 'form')).toHaveLength(1);
  } finally { vi.unstubAllGlobals(); }
});

it.each(['newer contacts', 'failed refresh', 401, 403])('recovers the identical challenge creation after a lost response and %s', async refresh => {
  const { ApiError } = await import('@/lib/api/client');
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 3, email: 'old@example.invalid', email_verified: true, pending_challenge: {
    id: 'previous-challenge', expires_at: '2026-11-17T11:00:00Z', delivery_mode: 'delivery_pending',
  } };
  state.request.mockReset(); state.refetch.mockReset();
  let fields = { channel: 'email', recipient: 'NEW@example.invalid', reauth: 'test-password-1234' };
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData {
    constructor() { super(); Object.entries(fields).forEach(([name, value]) => this.set(name, value)); }
  });
  try {
    const recovered = { id: 'original-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending' };
    state.request.mockResolvedValueOnce({ proof: 'original-proof' })
      .mockRejectedValueOnce(new TypeError('Response unavailable')).mockResolvedValue(recovered);
    const render = () => { state.index = 0; return elements(ContactDetails()); };
    const submit = (nodes: ReturnType<typeof render>) =>
      (nodes.find(node => node.type === 'form')!.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    const initial = render();
    const previousVerification = initial.filter(node => node.type === 'form')[1];
    submit(initial);
    // A second press cannot start another password proof while the first is in flight.
    submit(initial);
    expect(state.request).toHaveBeenCalledTimes(1);
    await state.running;
    expect(state.request).toHaveBeenCalledTimes(2);
    const original = state.request.mock.calls[1];
    const reference = original[1].headers['Idempotency-Key'];
    expect(reference).toBeTruthy();
    expect(original[0]).toBe('/v1/contacts/challenges');
    expect(JSON.parse(original[1].body)).toEqual({ channel: 'email', recipient: 'new@example.invalid', revision: 3, proof: 'original-proof' });
    expect(state.request.mock.calls[0][0]).toBe('/v1/accounts/reauthenticate');
    expect(JSON.parse(state.request.mock.calls[0][1].body).binding).toBe('email:new@example.invalid');
    fields = { channel: 'phone', recipient: '+96170123456', reauth: 'different-test-password-1234' };
    submit(initial);
    submit(render());
    (previousVerification.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    await state.running;
    expect(state.request).toHaveBeenCalledTimes(2);
    const pending = render();
    expect(pending.some(node => node.type === 'fieldset' && node.props.disabled)).toBe(true);
    expect(pending.some(node => node.type === 'button' && node.props.pending)).toBe(true);
    expect(pending.some(node => node.props.children === reference)).toBe(true);
    expect(pending.some(node => node.props.dateTime === '2026-11-17T11:00:00Z')).toBe(false);
    expect(pending.some(node => node.type === 'input' && node.props.name === 'code')).toBe(false);
    expect(pending.some(node => node.props.children === 'old@example.invalid')).toBe(true);
    if (refresh === 'newer contacts') {
      state.query.data = { revision: 9, email: 'old@example.invalid', pending_challenge: {
        id: 'different-challenge', expires_at: '2026-11-17T13:00:00Z', delivery_mode: 'delivery_pending',
      } };
    } else {
      state.query.isError = true;
      state.query.error = typeof refresh === 'number' ? new ApiError(refresh, 'denied', '') : new TypeError('Unavailable');
      if (typeof refresh === 'number') {
        const denied = render();
        const recovery = denied.find(node => node.props.children === 'Recover result')!;
        expect(denied.some(node => node.props.children === reference)).toBe(true);
        expect(denied.some(node => node.props.children === 'old@example.invalid')).toBe(false);
        expect(recovery.props.disabled).toBe(true);
        (recovery.props.onClick as () => void)(); await state.running;
        expect(state.request).toHaveBeenCalledTimes(2);
        state.query.data = undefined; state.query.error = new TypeError('Unavailable');
        expect(render().some(node => node.props.children === 'old@example.invalid')).toBe(false);
        state.query.isError = false; state.query.error = null; state.query.isPending = true;
        const loading = render();
        expect(loading.some(node => node.props.children === reference)).toBe(true);
        expect(loading.find(node => node.props.children === 'Recover result')!.props.disabled).toBe(true);
        state.query.isPending = false;
        state.query.data = { revision: 9, email: 'old@example.invalid', pending_challenge: null };
      } else state.query.data = undefined;
    }
    const recovery = render().find(node => node.props.children === 'Recover result')!;
    expect(recovery.props.disabled).toBe(false);
    (recovery.props.onClick as () => void)(); await state.running;
    expect(state.request).toHaveBeenCalledTimes(3);
    expect(state.request.mock.calls[2]).toEqual(original);
    expect(state.refetch).not.toHaveBeenCalled();
    const resolved = render();
    expect(resolved.some(node => node.props.children === reference)).toBe(false);
    expect(resolved.some(node => node.props.children === 'Recover result')).toBe(false);
    expect(resolved.some(node => node.props.dateTime === recovered.expires_at)).toBe(true);
    expect(resolved.some(node => node.type === 'fieldset' && node.props.disabled)).toBe(false);
    expect(resolved.filter(node => node.type === 'form')).toHaveLength(2);
  } finally { vi.unstubAllGlobals(); }
});

it.each([401, 403, 429, 503])('keeps challenge creation pending after uncertain response %i', async status => {
  const { ApiError } = await import('@/lib/api/client');
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 3, email: 'old@example.invalid', pending_challenge: null };
  state.request.mockReset();
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData {
    constructor() { super(); this.set('channel', 'phone'); this.set('recipient', '+٩٦١٧٠١٢٣٤٥٦'); this.set('reauth', 'test-password-1234'); }
  });
  try {
    state.request.mockResolvedValueOnce({ proof: 'original-proof' })
      .mockRejectedValueOnce(new ApiError(status, 'unavailable', ''))
      .mockResolvedValue({ id: 'original-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending' });
    const render = () => { state.index = 0; return elements(ContactDetails()); };
    (render().find(node => node.type === 'form')!.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    await state.running;
    const original = state.request.mock.calls[1];
    expect(JSON.parse(original[1].body).recipient).toBe('+96170123456');
    const reference = original[1].headers['Idempotency-Key'];
    const pending = render();
    expect(pending.some(node => node.props.children === reference)).toBe(true);
    expect(pending.some(node => node.type === 'fieldset' && node.props.disabled)).toBe(true);
    (pending.find(node => node.props.children === 'Recover result')!.props.onClick as () => void)(); await state.running;
    expect(state.request).toHaveBeenCalledTimes(3);
    expect(state.request.mock.calls[2]).toEqual(original);
    expect(render().some(node => node.props.children === reference)).toBe(false);
  } finally { vi.unstubAllGlobals(); }
});

it.each([400, 409, 422])('allows a new challenge only after definitive rejection %i', async status => {
  const { ApiError } = await import('@/lib/api/client');
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 3, pending_challenge: null };
  state.request.mockReset();
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData {
    constructor() { super(); this.set('channel', 'email'); this.set('recipient', 'new@example.invalid'); this.set('reauth', 'test-password-1234'); }
  });
  try {
    state.request.mockResolvedValueOnce({ proof: 'first-proof' })
      .mockRejectedValueOnce(new ApiError(status, 'rejected', ''))
      .mockResolvedValueOnce({ proof: 'second-proof' })
      .mockResolvedValue({ id: 'new-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending' });
    const render = () => { state.index = 0; return elements(ContactDetails()); };
    const submit = () => (render().find(node => node.type === 'form')!.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    submit(); await state.running;
    const rejected = render();
    expect(rejected.some(node => node.type === 'fieldset' && node.props.disabled)).toBe(false);
    expect(rejected.some(node => node.props.children === 'Recover result')).toBe(false);
    submit(); await state.running;
    expect(state.request).toHaveBeenCalledTimes(4);
    expect(state.request.mock.calls[3][1].headers['Idempotency-Key']).not.toBe(state.request.mock.calls[1][1].headers['Idempotency-Key']);
    expect(JSON.parse(state.request.mock.calls[3][1].body).proof).toBe('second-proof');
  } finally { vi.unstubAllGlobals(); }
});

it.each([401, 403])('recovers the identical verification after a lost response and denied retry %i', async status => {
  const { ApiError } = await import('@/lib/api/client');
  state.slots = []; state.query.isError = false; state.query.error = null;
  state.query.data = { revision: 1, email: 'old@example.invalid', pending_challenge: {
    id: 'test-challenge', expires_at: '2026-11-17T12:00:00Z', delivery_mode: 'delivery_pending',
  } };
  state.request.mockReset(); state.refetch.mockReset();
  state.refetch.mockResolvedValue({ isError: false });
  const NativeFormData = globalThis.FormData;
  vi.stubGlobal('FormData', class extends NativeFormData {
    constructor() { super(); this.set('code', '123456'); }
  });
  try {
    state.request.mockRejectedValueOnce(new TypeError('Response unavailable'))
      .mockRejectedValueOnce(new ApiError(status, 'denied', ''))
      .mockResolvedValue({ revision: 2 });
    const render = () => { state.index = 0; return elements(ContactDetails()); };
    const submit = () => {
      const form = render().filter(node => node.type === 'form')[1];
      (form.props.onSubmit as (event: unknown) => void)({ preventDefault() {}, currentTarget: {} });
    };
    submit(); await state.running;
    const original = state.request.mock.calls[0];
    const reference = original[1].headers['Idempotency-Key'];
    submit(); await state.running;
    expect(state.request.mock.calls[1]).toEqual(original);
    const hidden = render();
    expect(hidden.filter(node => node.type === 'form')).toHaveLength(1);
    expect(hidden.some(node => node.props.children === 'old@example.invalid')).toBe(false);
    expect(hidden.some(node => node.props.name === 'code')).toBe(false);
    expect(hidden.some(node => node.props.dateTime)).toBe(false);
    expect(hidden.some(node => node.type === 'fieldset' && node.props.disabled)).toBe(true);
    state.query.data = { revision: 9, pending_challenge: null };
    const reload = hidden.find(node => node.props.children === 'Retry' && typeof node.props.onClick === 'function')!;
    (reload.props.onClick as () => void)();
    await Promise.resolve(); await Promise.resolve();
    expect(render().some(node => node.props.children === reference)).toBe(true);
    submit(); await state.running;
    expect(state.request.mock.calls[2]).toEqual(original);
    expect(state.request).toHaveBeenCalledTimes(3);
    expect(render().filter(node => node.type === 'form')).toHaveLength(1);
  } finally { vi.unstubAllGlobals(); }
});
