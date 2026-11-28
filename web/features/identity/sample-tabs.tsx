'use client';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Card, State, buttonVariants } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { ApiError } from '@/lib/api/client';
import { backupRoles, dropSampleKey, heldSampleTab, holdSampleTab, primaryRoles, sampleFragment, sampleTab, sampleTabHref, type SampleRole, type SampleSet } from './sample-accounts';
import { enterSampleSession, openSessionSlot } from './session';
import { ErrorNotice, useIdentityCopy } from './shared';
import './rebuilt.css';

type Entry = { mode: 'kit'; set: SampleSet | null; key: string | null }
  | { mode: 'tab'; set: SampleSet; role: SampleRole; key: string | null; slot: Promise<string> };

/** The demo kit page (`/sample-tabs#set=<set>`, optionally with `&k=<key>`) and each sample
 * tab it opens (`/sample-tabs#set=<set>&role=<role>`). Ordinary tabs and other pages never
 * get a slot. The kit names no set by default, so it never opens an account by accident.
 * A reloaded sample tab that has not signed in yet tries again with what it holds. */
export default function SampleTabsView() {
  const { t } = useIdentityCopy();
  const [entry, setEntry] = useState<Entry | null>(null);
  const read = useRef(false);
  // Runs before any passive effect, so a fresh sample tab holds its slot before the
  // shell first restores a sign-in. The fragment is stripped from the address bar.
  useLayoutEffect(() => {
    if (read.current) return;
    read.current = true;
    const { set, role, key } = sampleFragment(window.location.hash);
    const bare = !window.location.hash;
    if (!bare) window.history.replaceState(null, '', window.location.pathname);
    if (set && role) holdSampleTab(set, role, key);
    // A reload finds no fragment: a tab still holding its key has not signed in, so it tries again.
    const held = bare ? heldSampleTab() : null;
    const tab = set && role ? { set, role, key } : held?.key ? held : null;
    setEntry(tab ? { mode: 'tab', ...tab, slot: openSessionSlot() } : { mode: 'kit', set, key });
  }, []);
  const title = entry?.mode === 'tab' ? t[`sample_${entry.role}`] : t.sampleTitle;
  return <PageFrame><PageHeader lead={t.sampleEyebrow} title={title} count={t.sampleOnly}/>
    <PageBody>{entry === null ? <State kind="loading" title={t.sampleTitle} body={t.working}/>
      : entry.mode === 'kit' ? <SampleKit set={entry.set} demoKey={entry.key}/>
      : <SampleTab set={entry.set} role={entry.role} demoKey={entry.key} slot={entry.slot}/>}</PageBody>
  </PageFrame>;
}

function SampleKit({ set, demoKey }: { set: SampleSet | null; demoKey: string | null }) {
  const { locale, t } = useIdentityCopy();
  if (set === null) return <div className="account-stack" data-sample-kit="">
    <p>{t.sampleIntro}</p><p role="status">{t.sampleNoSet}</p>
  </div>;
  const card = (role: SampleRole) => {
    const { email, site } = sampleTab(set, role);
    // A role the sample list does not name for this set gets no link, and a kit without
    // the key opens no tabs: a tab signs in only with the key. The Operator card shows no
    // address: Identity alone knows which account the site's operator link opens.
    const open = demoKey && <a className={buttonVariants()} data-variant="default" data-size="default" href={sampleTabHref(locale, set, role, demoKey)} target="_blank" rel="noopener noreferrer">
      <span className="bt-button-label">{t.sampleOpen}</span>
    </a>;
    return <Card key={role}><h2>{t[`sample_${role}`]}</h2>
      {site ? <><p>{t.sampleOperatorAccount}</p>{open}</>
        : email === null ? <p role="status">{t.sample_account_unavailable}</p> : <><p><bdi>{email}</bdi></p>{open}</>}</Card>;
  };
  return <div className="account-stack" data-sample-kit={set}>
    <p>{t.sampleIntro}</p><p>{t[set === 'demo' ? 'sampleSetDemo' : 'sampleSetClickTest']}</p>
    <p role="status">{demoKey ? t.sampleKeyHeld : t.sampleNoKey}</p>
    <div className="account-grid">{primaryRoles.map(card)}</div>
    <h2>{t.sampleBackups}</h2><div className="account-grid">{backupRoles.map(card)}</div>
  </div>;
}

function SampleTab({ set, role, demoKey, slot }: { set: SampleSet; role: SampleRole; demoKey: string | null; slot: Promise<string> }) {
  const { locale, t } = useIdentityCopy();
  const router = useRouter();
  const { email, site, start: page } = sampleTab(set, role);
  const reachable = site || email !== null;
  const [entering, setEntering] = useState(Boolean(demoKey && reachable));
  const [notice, setNotice] = useState<Notice | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reload, setReload] = useState(false);
  const started = useRef(false);
  const start = `/${locale}${page}`;
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        await slot;
        if (!demoKey || !reachable) return;
        await enterSampleSession(set, role, demoKey);
        dropSampleKey();
        router.replace(start);
      } catch (failure) {
        // The switch off answers 404. There is no password to fall back to: the seed
        // gives no sample account a usable one, and Identity refuses typed sign-in here.
        // A key Identity calls not valid is forgotten; any other key stays in this tab's
        // own storage, so reloading the tab tries again without the kit. A temporary failure
        // that outlasted the quiet retries is no error to show: the tab just says to reload.
        // An account that is not ready (the seed has not run, or the site names no operator
        // account) is a plain status too, and the tab keeps its key so a reload tries again.
        if (failure instanceof ApiError && failure.code === 'demo_entry_refused') dropSampleKey();
        if (failure instanceof ApiError && failure.status === 404) setNotice('sampleSwitchOff');
        else if (failure instanceof ApiError && failure.status === 409 && isNotReady(failure.code)) setNotice(failure.code);
        else {
          const again = heldSampleTab()?.key === demoKey;
          const temporary = !(failure instanceof ApiError) || failure.status === 503;
          if (!(again && temporary)) setError(failure);
          setReload(again);
        }
        setEntering(false);
      }
    })();
  }, [demoKey, reachable, role, router, set, slot, start]);
  if (entering) return <State kind="loading" title={t.sampleEntering} body={t.sampleEnteringBody}/>;
  return <Card><SampleStatus set={set} role={role}>
    {notice ? <p role="status">{t[notice]}</p> : !demoKey && <p role="status">{t.sampleTabNoKey}</p>}
    <ErrorNotice error={error}/>
    {reload && <p role="status">{t.sampleReload}</p>}
  </SampleStatus></Card>;
}

type Notice = 'sampleSwitchOff' | 'sample_account_unavailable' | 'operator_link_unavailable';
function isNotReady(code: string): code is 'sample_account_unavailable' | 'operator_link_unavailable' {
  return code === 'sample_account_unavailable' || code === 'operator_link_unavailable';
}

/** What a sample tab shows when it is not signed in: its account and one plain status line.
 * The Operator tab names no address, only that it is the site's own operator account. */
function SampleStatus({ set, role, signedOut = false, children }: { set: SampleSet; role: SampleRole; signedOut?: boolean; children: React.ReactNode }) {
  const { t } = useIdentityCopy();
  const { email, site } = sampleTab(set, role);
  const marker = signedOut ? { 'data-sample-signed-out': role } : { 'data-sample-tab': role };
  return <div className="account-stack" {...marker} data-sample-set={set}>
    {site ? <><p>{t.sampleOperatorAccount}</p>{children}</>
      : email === null ? <p role="status">{t.sample_account_unavailable}</p> : <><p><bdi>{email}</bdi></p>{children}</>}
  </div>;
}

/** A signed-out sample tab's status, shown on the account page instead of the password form:
 * a sample tab signs in only from its link, and Identity refuses a typed sign-in there. */
export function SampleTabSignedOut({ set, role }: { set: SampleSet; role: SampleRole }) {
  const { t } = useIdentityCopy();
  return <SampleStatus set={set} role={role} signedOut><p role="status">{t.sampleSignedOut}</p></SampleStatus>;
}
