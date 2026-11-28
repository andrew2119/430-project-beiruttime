'use client';
import { useEffect, useSyncExternalStore } from 'react';
import { request, ApiError } from '@/lib/api/client';
import { setAccessContext } from '@/shell/private-state';
import type { Role } from '@/registry-types';
import type { Session } from '@contracts/contracts-identity/accounts';
import type { SampleRole, SampleSet } from './sample-accounts';

const base = '/api/web/v1/identity/v1/accounts';
const sampleEntry = '/api/web/v1/identity/v1/demo-entry/sessions';
// A sample tab holds a slot: a random per-tab name, kept in sessionStorage, that names
// its own refresh cookie, tab channel and refresh lock. It is not a credential.
// Tabs without one keep the shared sign-in exactly as before.
const slotKey = 'bt-session-slot';
const slotPattern = /^[A-Za-z0-9_-]{22}$/;
function sessionSlot(): string | null {
  try { const slot = sessionStorage.getItem(slotKey); return slot && slotPattern.test(slot) ? slot : null; }
  catch { return null; }
}
function scoped(name: string) { const slot = sessionSlot(); return slot ? `${name}:${slot}` : name; }
function slotted(init: RequestInit = {}): RequestInit {
  const slot = sessionSlot();
  if (!slot) return init;
  const headers = new Headers(init.headers);
  headers.set('X-BT-Session-Slot', slot);
  return { ...init, headers };
}
let current: Session | null = null;
let generation = 0;
let restored = false;
let leaving = false;
let refreshFlight: Promise<Session | null> | null = null;
let signInFlight: Promise<Session> | null = null;
let restoreState: 'restoring' | 'signed-out' | 'unavailable' | 'authenticated' = 'restoring';
const listeners = new Set<() => void>();
let channel: BroadcastChannel | null = null;
function publish(session: Session | null) {
  current = session;
  restoreState = session ? 'authenticated' : 'signed-out';
  setAccessContext(session?.access_fingerprint ?? null, session?.principal.roles as Role[] | undefined);
  listeners.forEach(callback => callback());
}
function broadcast() { channel?.postMessage('signed-out'); }
function setup() {
  const name = scoped('bt-identity-v1');
  if (channel?.name !== name && typeof BroadcastChannel !== 'undefined') {
    channel?.close();
    channel = new BroadcastChannel(name);
    channel.onmessage = event => {
      if (event.data === 'signed-out') { generation++; leaving = true; publish(null); }
      if (event.data === 'session-changed') {
        generation++; leaving = false; restored = false; publish(null);
        void (refreshFlight ?? Promise.resolve()).catch(() => null).then(() => refreshSession()).catch(() => null);
      }
    };
  }
}
export function acceptSession(session: Session) {
  generation++; leaving = false; restored = true; setup(); publish(session); channel?.postMessage('session-changed');
}
export async function refreshSession(): Promise<Session | null> {
  if (leaving) return null;
  setup();
  if (!refreshFlight) {
    if (!current) { restoreState = 'restoring'; listeners.forEach(callback => callback()); }
    const expected = generation;
    const refresh = async () => {
      if (leaving || generation !== expected) return current;
      try {
        const session = await request<Session>(`${base}/refresh`, slotted({ method: 'POST' }));
        if (!leaving && generation === expected) { restored = true; publish(session); }
        return generation === expected && !leaving ? current : null;
      } catch (error) {
        if (generation === expected && error instanceof ApiError && error.status === 401) { restored = true; publish(null); }
        if (error instanceof ApiError && error.status === 401) return null;
        if (generation === expected && !leaving) { restoreState = 'unavailable'; listeners.forEach(callback => callback()); }
        throw error;
      }
    };
    // One same-origin refresh admission, logout fences late answers.
    const coordinated = navigator.locks ? navigator.locks.request(scoped('bt-refresh-v1'), refresh) as unknown as Promise<Session | null> : refresh();
    refreshFlight = coordinated.finally(() => { refreshFlight = null; });
  }
  return refreshFlight;
}
export function beginSession(action: 'login' | 'register', body: string, key: string): Promise<Session> {
  return admitSession(`${base}/${action}`, { method:'POST', headers:{'Content-Type':'application/json','Idempotency-Key':key}, body });
}
// Tabs of one set opened together can find entry busy for a moment. Only a temporary
// refusal is tried again: 503, which the API client also reports for its own timeout or a
// lost connection. Every other answer is final at once. The seven pauses grow from about
// 250 ms to 4 s, with a little jitter so the tabs spread out, and together they take
// 11.8 to 15.75 s, longer than entry's ten-second breaker cooldown.
export const sampleEntryAttempts = 8;
export function sampleEntryPause(retry: number) {
  return Math.min(4000, 250 * 2 ** retry) * (0.75 + Math.random() * 0.25);
}
/** Signs this sample tab in without a password while the demo switch is on. */
export async function enterSampleSession(set: SampleSet, role: SampleRole, key: string): Promise<Session> {
  if (!sessionSlot()) throw new ApiError(400, 'invalid_session_slot', '');
  const init = { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ set, role, key }) };
  for (let attempt = 1; ; attempt++) {
    try { return await admitSession(sampleEntry, init); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 503 || attempt >= sampleEntryAttempts) throw error;
      const seen = generation;
      await new Promise(done => setTimeout(done, sampleEntryPause(attempt - 1)));
      // A sign-out or a new slot while waiting ends the attempts.
      if (generation !== seen || leaving || !sessionSlot()) throw new ApiError(401, 'session_changed', '');
    }
  }
}
/** Gives this tab a fresh slot of its own. A tab that already holds a slot signs that slot
 * out first, so no orphaned sample sign-in stays behind. A tab without one switches
 * synchronously, before any refresh of the shared sign-in can start. */
export async function openSessionSlot(): Promise<string> {
  if (sessionSlot()) await signOut().catch(() => undefined);
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const slot = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  sessionStorage.setItem(slotKey, slot);
  if (sessionSlot() !== slot) throw new ApiError(400, 'invalid_session_slot', '');
  // A fresh slot has no refresh cookie, so there is nothing to restore: the shell sends no
  // refresh for it, and tabs opened together never crowd ordinary Identity calls.
  generation++; leaving = false; restored = true; publish(null); setup();
  return slot;
}
export function hasSessionSlot() { return sessionSlot() !== null; }
async function admitSession(path: string, init: RequestInit): Promise<Session> {
  if (signInFlight) throw new ApiError(409, 'session_pending', '');
  const expected = ++generation;
  leaving = false;
  const submit = async () => {
    if (generation !== expected || leaving) throw new ApiError(401, 'session_changed', '');
    const session = await request<Session>(path, slotted(init));
    if (generation !== expected || leaving) throw new ApiError(401, 'session_changed', '');
    acceptSession(session);
    return session;
  };
  const admitted = async () => {
    await refreshFlight?.catch(() => null);
    return navigator.locks ? await navigator.locks.request(scoped('bt-refresh-v1'), submit) : await submit();
  };
  signInFlight = admitted().finally(() => { signInFlight = null; });
  return signInFlight;
}
export async function signOut() {
  generation++; leaving = true; publish(null); broadcast();
  const revoke = () => request(`${base}/logout`, slotted({ method: 'POST' }));
  // A prior refresh must finish before logout reads the cookie. Its answer cannot publish.
  await refreshFlight?.catch(() => null);
  await signInFlight?.catch(() => null);
  if (navigator.locks) await navigator.locks.request(scoped('bt-refresh-v1'), revoke); else await revoke();
}
export function useSession() {
  const session = useSyncExternalStore(callback => { listeners.add(callback); return () => listeners.delete(callback); }, () => current, () => null);
  useEffect(() => { if (!restored && !leaving) void refreshSession().catch(() => { /* Feature renders explicit unavailable recovery. */ }); }, []);
  return session;
}
export function useSessionState() {
  return useSyncExternalStore(callback => { listeners.add(callback); return () => listeners.delete(callback); }, () => restoreState, () => 'restoring' as const);
}
export type AuthenticatedRequestInit = RequestInit & { accessFingerprint?: string };
export async function authenticatedRequest<T>(path: string, options: AuthenticatedRequestInit = {}): Promise<T> {
  const { accessFingerprint, ...init } = options;
  let session = current ?? await refreshSession();
  if (!session) throw new ApiError(401, 'unauthorized', '');
  const scope = accessFingerprint ?? session.access_fingerprint;
  const expected = generation;
  const invoke = async () => {
    if (generation !== expected || leaving || session!.access_fingerprint !== scope || current?.access_fingerprint !== scope) throw new ApiError(401, 'unauthorized', '');
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${session!.access_token}`);
    const result = await request<T>(path, { ...init, headers });
    if (generation !== expected || leaving || current?.access_fingerprint !== scope) throw new ApiError(401, 'unauthorized', '');
    return result;
  };
  try { return await invoke(); }
  catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || generation !== expected || leaving || current?.access_fingerprint !== scope) throw error;
    session = await refreshSession();
    if (!session) throw new ApiError(401, 'unauthorized', '');
    return invoke();
  }
}
export function safeReturnPath(value: string | null): string {
  if (!value || /[\\\u0000-\u0020#]/.test(value) || !value.startsWith('/') || value.startsWith('//')) return '/account';
  const candidate = value.split('?')[0];
  if (/(?:^|\/)\.{1,2}(?:\/|$)/.test(candidate) || /%(?:2f|5c|2e|0[0-9a-f]|1[0-9a-f]|7f)/i.test(candidate)) return '/account';
  let parsed: URL;
  try { parsed = new URL(value, 'https://beirut-time.invalid'); } catch { return '/account'; }
  if (parsed.origin !== 'https://beirut-time.invalid' || /%(?:2f|5c|2e|0[0-9a-f]|1[0-9a-f]|7f)/i.test(parsed.pathname)) return '/account';
  const path = (parsed.pathname.replace(/^\/(en|ar)(?=\/|$)/, '') || '/') + parsed.search;
  const allowed = ['/watches','/search','/buyer','/seller/listings','/seller/dashboard','/seller/verification','/seller/auctions','/checkout','/custom-requests','/consent','/account','/inbox','/customize','/services','/prices','/buying','/business','/business-intake','/operations/verification','/operations/dashboard','/operations/moderation'];
  return allowed.some(prefix => path === prefix || path.startsWith(prefix + '/') || path.startsWith(prefix + '?')) ? path : '/account';
}
export function signInHref(next: string, locale: 'en' | 'ar' = 'en') { return `/${locale}/account?next=${encodeURIComponent(safeReturnPath(next))}`; }
export const accountApi = base;
