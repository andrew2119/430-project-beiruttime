'use client';
import { useEffect, useRef, useState } from 'react';
import { Button, ButtonLink, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import type { ExternalOperation, ExternalState } from '@contracts/contracts-identity/external-sign-in';
import { OperationController, type Transport } from './controller';
import './styles.css';

const copy = {
  en: {
    title: 'External account sign-in', lead: 'Your account permissions are checked separately.',
    ready: ['Continue securely', 'External sign-in is not connected here. You can use ordinary sign-in.'],
    pending: ['Sign-in pending', 'The result is uncertain. Check the same reference before trying another sign-in.'],
    signed_in: ['Identity confirmed', 'Continue to your account. Current access is checked there.'],
    linked: ['Account linked', 'Both identities were confirmed. Continue to your account.'],
    denied: ['Sign-in unavailable', 'Use ordinary sign-in or account recovery. Matching email alone cannot link accounts.'],
    stale: ['Access changed', 'Return to sign-in and confirm your current account again.'],
    unavailable: ['External sign-in unavailable', 'Use ordinary sign-in or check the same reference again.'],
    retry: 'Check the same reference', checking: 'Checking sign-in', account: 'Sign in or recover your account',
    continue: 'Continue to account', reference: 'Action reference',
  },
  ar: {
    title: 'الدخول بحساب خارجي', lead: 'يتم التحقق من صلاحيات حسابك بشكل مستقل.',
    ready: ['المتابعة بأمان', 'الدخول الخارجي غير متصل هنا. يمكنك استخدام تسجيل الدخول المعتاد.'],
    pending: ['تسجيل الدخول قيد الانتظار', 'النتيجة غير مؤكدة. تحقّق من المرجع نفسه قبل محاولة تسجيل دخول أخرى.'],
    signed_in: ['تم تأكيد الهوية', 'تابع إلى حسابك. سيتم التحقق من صلاحية الوصول الحالية هناك.'],
    linked: ['تم ربط الحساب', 'تم تأكيد الهويتين. تابع إلى حسابك.'],
    denied: ['تعذّر تسجيل الدخول', 'استخدم تسجيل الدخول المعتاد أو استرداد الحساب. تطابق البريد وحده لا يسمح بربط الحسابات.'],
    stale: ['تغيّر الوصول', 'عُد إلى تسجيل الدخول وأكّد حسابك الحالي مجددًا.'],
    unavailable: ['الدخول الخارجي غير متاح', 'استخدم تسجيل الدخول المعتاد أو تحقّق من المرجع نفسه مجددًا.'],
    retry: 'التحقق من المرجع نفسه', checking: 'جارٍ التحقق من تسجيل الدخول', account: 'تسجيل الدخول أو استرداد الحساب',
    continue: 'المتابعة إلى الحساب', reference: 'مرجع الإجراء',
  },
};

type Props = {accessPartition: string; operation?: ExternalOperation; transport?: Transport};
export default function ExternalSignInView(props: Props) {
  return <PrivateView key={props.accessPartition} accessPartition={props.accessPartition} operation={props.operation} transport={props.transport}/>;
}
function PrivateView({operation, transport}: Props) {
  const locale = useLocale(), t = copy[locale];
  const [snapshot, setSnapshot] = useState({source: operation, current: operation});
  const [activeTransport, setActiveTransport] = useState(() => transport);
  const [busy, setBusy] = useState(false);
  if (snapshot.source !== operation) {
    setSnapshot({source: operation, current: operation});
    setBusy(false);
  }
  if (activeTransport !== transport) {
    setActiveTransport(() => transport);
    setBusy(false);
  }
  const current = snapshot.source === operation ? snapshot.current : operation;
  const controller = useRef<OperationController | null>(null);
  useEffect(() => {
    const owner = transport ? new OperationController(transport) : null;
    controller.current = owner;
    return () => { owner?.clear(); controller.current = null; };
  }, [transport, operation]);
  const state: ExternalState = current?.state ?? 'unavailable';
  const success = state === 'signed_in' || state === 'linked';
  async function retry() {
    const owner = controller.current;
    if (!current || !owner || busy) return;
    setBusy(true);
    const source = operation;
    const answer = await owner.retry(current);
    if (controller.current !== owner) return;
    if (answer) setSnapshot({source, current: answer});
    setBusy(false);
  }
  return <PageFrame>
    <PageHeader title={t.title} lead={t.lead}/>
    <PageBody>
      <State title={busy ? t.checking : t[state][0]} body={t[state][1]}
        kind={busy ? 'loading' : state === 'denied' || state === 'stale' ? 'error' : 'empty'}>
        {current && <p className="bt-text l22-external-reference">{t.reference}: <bdi>{current.operation_id}</bdi></p>}
        {current && transport && ['pending','unavailable'].includes(state) && <Button busy={busy} onClick={() => { void retry(); }}>{t.retry}</Button>}
        <ButtonLink href={`/account?lang=${locale}`}>{success ? t.continue : t.account}</ButtonLink>
      </State>
    </PageBody>
  </PageFrame>;
}
