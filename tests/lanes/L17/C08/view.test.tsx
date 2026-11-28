import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ locale: 'en', session: 'authenticated', data: null as unknown, denied: false }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => state.locale }));
vi.mock('@/shell/access-context', () => ({ useAccessContext: () => ({ fingerprint: 'scope-1' }) }));
vi.mock('@/features/identity/session', () => ({ useSession: () => null, useSessionState: () => state.session }));
vi.mock('@/lib/page-speed/read', () => ({ usePageRead: () => ({ data: state.data, isError: state.denied, error: state.denied ? new ApiError(403, 'denied', '') : null, isLoading: false }) }));
vi.mock('@/features/brand-assessment/api', () => ({ assessmentRead: vi.fn(), submit: vi.fn(), lookupOperation: vi.fn() }));
import { ApiError } from '../../../../web/lib/api/client';
import { AssessmentView, AssessmentForm, SavedAssessment, reconcileAssessment } from '../../../../web/features/brand-assessment/view';
import { words } from '../../../../web/features/brand-assessment/copy';

describe('Assessment page', () => {
  it.each(['en', 'ar'] as const)('mounts the functional request form in %s', locale => {
    state.locale = locale; state.session = 'authenticated';
    const html = renderToStaticMarkup(<AssessmentView/>);
    expect(html).toContain(words[locale].request);
    expect(html).toContain(words[locale].open);
    expect(html).toContain('<input');
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).not.toContain('<main');
  });
  it('clears private fields behind denied access', () => {
    state.session = 'signed-out';
    const html = renderToStaticMarkup(<AssessmentView/>);
    expect(html).toContain(words.ar.denied);
    expect(html).not.toContain('<input');
  });
  it('conceals a retained private record when current record access is denied', () => {
    state.data = { state: 'assessed', current_scope: { base_id: 'private-base', caliber_id: 'private-caliber', option_snapshots: [] }, limitations: 'private-findings' };
    state.denied = true;
    const html = renderToStaticMarkup(<AssessmentForm/>);
    expect(html).toContain(words.ar.denied);
    for (const value of ['private-base', 'private-findings', '<input', '<textarea']) expect(html).not.toContain(value);
    state.denied = false; state.data = null;
  });
  it.each(['en', 'ar'] as const)('offers retained pending recovery on a fresh form in %s', locale => {
    state.locale = locale; state.denied = false;
    state.data = { subject_id: 'request', operation_id: 'retained-operation', state: 'correction_pending',
      pending_reason: 'catalog_receipt', next_actor: 'catalog' };
    const first = renderToStaticMarkup(<AssessmentForm/>);
    const remounted = renderToStaticMarkup(<AssessmentForm/>);
    for (const html of [first, remounted]) {
      expect(html).toContain('retained-operation');
      expect(html).toContain(words[locale].pendingBody);
      expect(html).toContain(words[locale].retry);
    }
    state.data = null;
  });
  it.each(['en', 'ar'] as const)('wraps maximum permitted follow-up and action references in %s', locale => {
    state.locale = locale; state.denied = false;
    const responsible = 'r'.repeat(100), operation = 'o'.repeat(100);
    state.data = { subject_id: 'request', operation_id: operation, state: 'correction_pending',
      responsible_operator_id: responsible, pending_reason: 'catalog_receipt', next_actor: 'catalog' };
    const html = renderToStaticMarkup(<AssessmentForm/>);
    for (const reference of [responsible, operation]) {
      expect(html).toContain(`<p class="bt-text">${words[locale][reference === responsible ? 'next' : 'operation']}: <bdi>${reference}</bdi></p>`);
    }
    const source = readFileSync(new URL('../../../../web/features/brand-assessment/view.tsx', import.meta.url), 'utf8');
    expect(source).toContain('{operation && <p className="bt-text">{t.operation}: <bdi>{operation.operation_id}</bdi></p>}');
    state.data = null;
  });
  it('renders persisted attributed findings separately' , () => {
    state.locale = 'en';
    const html = renderToStaticMarkup(<SavedAssessment current={{ assessment_id: 'record-1', assessment_revision: 1, assessor_id: 'person-1', feasibility: 'feasible', parts: ['spring'], limitations: 'Fit measured', lead_time_basis: 'Supplier confirmed' } as never}/>);
    for (const value of ['record-1', 'person-1', 'spring', 'Fit measured', 'Supplier confirmed', 'Feasible']) expect(html).toContain(value);
  });
  it.each(['en', 'ar'] as const)('wraps maximum permitted saved findings in %s', locale => {
    state.locale = locale;
    const parts = Array.from({ length: 50 }, (_, index) => `${index}`.padEnd(300, 'x'));
    const limitations = 'قيدABC😀'.repeat(500).slice(0, 4000);
    const basis = 'x'.repeat(2000);
    const assessor = 'p'.repeat(100);
    const html = renderToStaticMarkup(<SavedAssessment current={{ assessment_id: 'a'.repeat(100),
      assessment_revision: 1, assessor_id: assessor, parts, limitations, lead_time_basis: basis } as never}/>);
    expect(html).toContain('class="bt-assessment-scope"');
    for (const value of [...parts, limitations, basis, assessor]) expect(html).toContain(value);
    const css = readFileSync(new URL('../../../../web/features/brand-assessment/styles.css', import.meta.url), 'utf8');
    expect(css).toMatch(/\.bt-assessment-scope dd\s*\{[^}]*min-inline-size: 0;[^}]*overflow-wrap: anywhere;/);
  });
  it('has complete parallel recovery and action text', () => {
    expect(Object.keys(words.en).sort()).toEqual(Object.keys(words.ar).sort());
    for (const text of Object.values(words.ar)) expect(text.trim().length).toBeGreaterThan(0);
  });
});

describe('Saved assessment reconciliation', () => {
  const saved = { subject_id: 'request', organization_id: 'brand', actor_id: 'person', watch_id: 'watch',
    request_revision: 1, capability_revision: 1, assignment_revision: 1, revision: 2,
    operation_id: 'stable-operation', state: 'assessed', assessment_id: 'private-assessment',
    limitations: 'private-findings' };
  it.each(['current_request_revision', 'current_capability_revision'])(
    'conceals saved findings after %s changes', field => {
      const fresh = { ...saved, revision: 1, state: 'revised', assessment_id: undefined,
        limitations: undefined, [field]: 2 };
      const current = reconcileAssessment(saved as never, fresh as never);
      expect(current).toBe(fresh);
      expect(saved.operation_id).toBe('stable-operation');
      const html = renderToStaticMarkup(<SavedAssessment current={current!}/>);
      expect(html).not.toContain('private-assessment');
      expect(html).not.toContain('private-findings');
    });
  it('keeps a newer saved response only while source bindings match', () => {
    expect(reconcileAssessment(saved as never, { ...saved, revision: 1 } as never)).toBe(saved);
    const fresh = { ...saved, revision: 3, assignment_revision: 2, assessment_id: undefined };
    expect(reconcileAssessment(saved as never, fresh as never)).toBe(fresh);
  });
});
