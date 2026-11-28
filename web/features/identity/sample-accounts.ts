import { useSyncExternalStore } from 'react';
import sampleList from '@contracts/contracts-identity/accounts/sample-accounts.v1.json';

/** Each sample role's start page. */
const starts = {
  buyer: '/watches',
  seller: '/seller/verification',
  staff: '/business',
  operator: '/operations/dashboard',
  rival: '/watches',
} as const;
export type SampleRole = keyof typeof starts;
/** The demo seed's two sample sets: `demo` for the class, `click-test` for rehearsals. */
export const sampleSets = ['demo', 'click-test'] as const;
export type SampleSet = typeof sampleSets[number];
type Listed = { set: string; role: string; email: string; account_id: string };
const listed = new Map((sampleList.accounts as Listed[]).map(entry => [`${entry.set}:${entry.role}`, entry.email]));
/** The account one set's tab holds for a role. A sample role holds its account from the one
 * sample list that Identity also enforces (packages/contracts-identity/accounts/sample-accounts.v1.json);
 * every listed account is a demo seed account, and a role the list does not name has no address
 * and no link. The Operator tab is the site's own operator account, which Identity alone names
 * from its settings, so the page never knows its address: `site` is true and `email` is null. */
export function sampleTab(set: SampleSet, role: SampleRole): { email: string | null; site: boolean; start: string } {
  if (role === 'operator') return { email: null, site: true, start: starts[role] };
  return { email: listed.get(`${set}:${role}`) ?? null, site: false, start: starts[role] };
}
/** The four demo tabs in storyline order, then the backup. */
export const primaryRoles = ['buyer', 'seller', 'staff', 'operator'] as const satisfies readonly SampleRole[];
export const backupRoles = ['rival'] as const satisfies readonly SampleRole[];
const keyPattern = /^[A-Za-z0-9_-]{32,200}$/;

export function sampleRole(value: string | null | undefined): SampleRole | null {
  return value && Object.hasOwn(starts, value) ? value as SampleRole : null;
}
export function sampleSet(value: string | null | undefined): SampleSet | null {
  return sampleSets.find(set => set === value) ?? null;
}
/** Reads `#set=<set>&role=<role>&k=<key>`. The fragment never reaches the server; the caller strips it. */
export function sampleFragment(hash: string): { set: SampleSet | null; role: SampleRole | null; key: string | null } {
  const values = new URLSearchParams(hash.replace(/^#/, ''));
  const key = values.get('k');
  return { set: sampleSet(values.get('set')), role: sampleRole(values.get('role')), key: key && keyPattern.test(key) ? key : null };
}
/** One sample tab's address. The key, when the kit holds one, travels only in the fragment. */
export function sampleTabHref(locale: 'en' | 'ar', set: SampleSet, role: SampleRole, key: string | null) {
  const values = new URLSearchParams({ set, role });
  if (key) values.set('k', key);
  return `/${locale}/sample-tabs#${values}`;
}

// A sample tab notes its set and role in its own session storage, so it still shows its
// own status after a sign-out. Neither is a credential. Its key waits there too, only
// until the tab signs in, so reloading a tab that could not sign in tries again on its own.
// Session storage belongs to this one tab and ends when it closes: the kit opens each tab
// with noopener, so no other tab gets a copy (only the browser's own Duplicate tab copies it).
const heldName = 'bt-sample-tab';
const heldKeyName = 'bt-sample-entry-key';
export type HeldSampleTab = { set: SampleSet; role: SampleRole; key: string | null };
function readHeld(raw: string | null): HeldSampleTab | null {
  const [set, role, extra] = (raw ?? '').split(':');
  const held = { set: sampleSet(set), role: sampleRole(role) };
  if (!held.set || !held.role || extra !== undefined) return null;
  let key: string | null = null;
  try { key = sessionStorage.getItem(heldKeyName); } catch { /* No storage: nothing is held. */ }
  return { set: held.set, role: held.role, key: key && keyPattern.test(key) ? key : null };
}
function heldValue() {
  try { return sessionStorage.getItem(heldName); } catch { return null; }
}
/** The sample tab this tab holds, with its key while it has not signed in yet. */
export function heldSampleTab(): HeldSampleTab | null {
  return readHeld(heldValue());
}
/** Notes that this tab is the sample tab for one set and role, with its key if it has one. */
export function holdSampleTab(set: SampleSet, role: SampleRole, key: string | null) {
  try {
    sessionStorage.setItem(heldName, `${set}:${role}`);
    if (key && keyPattern.test(key)) sessionStorage.setItem(heldKeyName, key);
    else sessionStorage.removeItem(heldKeyName);
  } catch { /* No storage: the tab cannot hold its slot either, so openSessionSlot fails and it cannot sign in. */ }
}
/** Forgets this tab's key: once it has signed in, or once Identity says the key is not valid. */
export function dropSampleKey() {
  try { sessionStorage.removeItem(heldKeyName); } catch { /* Nothing was held. */ }
}
const unchanging = () => () => undefined;
/** The sample tab this tab holds, for a view: null on the server and in every ordinary tab. */
export function useHeldSampleTab(): HeldSampleTab | null {
  return readHeld(useSyncExternalStore(unchanging, heldValue, () => null));
}
