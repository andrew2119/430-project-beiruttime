import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { ListingProof, StaffWorkspace } from '@contracts/contracts-identity/businesses/workspace_v2';
import { staffWorkspaceFixture } from '../../../tests/lanes/L20/BUSINESS/workspace-fixtures';
import en from './en.json';
import ar from './ar.json';
const state = vi.hoisted(() => ({locale:'en'}));
vi.mock('@/shell/locale-context', () => ({useLocale:() => state.locale}));
vi.mock('@/features/identity/session', () => ({useSession:() => ({principal:{actor:{subject_id:'seller'}},access_token:'memory'})}));
vi.mock('@/shell/access-context', () => ({useAccessContext:() => ({fingerprint:'current'})}));
vi.mock('next/navigation', () => ({usePathname:() => '/business',useRouter:() => ({push:vi.fn()})}));
import { ProofControls } from './possession';
import { StaffEditor } from './membership';
const proof:ListingProof = {subject_id:'seller',watch_id:'watch',watch_revision:2,listing_revision:3,revision:4,state:'issued',challenge_id:'challenge',expires_at:'2026-11-18T00:00:00Z',assignment_revision:1,reviewer_id:null,can_issue:false,can_submit:true,can_assign:false,can_decide:false,evidence_available:false};
const workspace:StaffWorkspace = {organization_id:'selected-business',actor_id:'administrator',can_manage:true,ceiling_revision:2,ceiling:['business.records.read'],responsibilities_current:true,jobs:[{job_id:'active-job',responsible_id:'colleague',revision:5}],replacements:[{subject_id:'qualified-replacement',revision:2}],items:[],total:1000,page:1,page_size:25};
describe.each(['en','ar'])('private business forms in %s', locale => {
  it('renders a listing-specific private photo and code form without saving bytes', () => {
    state.locale=locale;const copy=locale==='ar'?ar:en;
    const html=renderToStaticMarkup(<ProofControls proof={proof} refresh={vi.fn()} />);
    expect(html).toContain(copy.privatePhoto);
    expect(html).toContain('type="file"');expect(html).toContain('name="code"');
    expect(html).toContain(copy.safePhoto);expect(html).not.toContain('name="reviewer"');
  });
  it('shows assigned review, reasoned verdict and protected evidence controls', () => {
    state.locale=locale;const copy=locale==='ar'?ar:en;
    const html=renderToStaticMarkup(<ProofControls proof={{...proof,can_submit:false,can_assign:true,can_decide:true,evidence_available:true,state:'pending'}} refresh={vi.fn()} />);
    expect(html).toContain(copy.openEvidence);expect(html).toContain('name="reviewer"');
    expect(html).toContain('name="verdict"');expect(html).toContain('name="reason"');
    expect(html).not.toContain('type="file"');
  });
  it('denies all proof controls when current permissions are absent', () => {
    state.locale=locale;const copy=locale==='ar'?ar:en;
    const html=renderToStaticMarkup(<ProofControls proof={{...proof,can_submit:false}} refresh={vi.fn()} />);
    expect(html).toContain(copy.noAuthority);expect(html).not.toContain('<form');
  });
  it('offers only ordinary permissions within the ceiling and qualified replacements', () => {
    state.locale=locale;const copy=locale==='ar'?ar:en;
    const html=renderToStaticMarkup(<StaffEditor data={workspace} member={{subject_id:'colleague',revision:3,state:'active',ordinary:true,permissions:['business.records.read']}} refresh={vi.fn()} />);
    expect(html).toContain(copy.recordsRead);expect(html).not.toContain(copy.stockWrite);
    expect(html).not.toContain(copy.staffManage);expect(html).toContain('qualified-replacement');
    expect(html).toContain('name="replacement"');expect(html).toContain('value="suspend"');expect(html).toContain('value="remove"');
    expect(html).not.toContain('identity.membership.manage');
  });
  it('preserves mixed user text without interpreting it as markup', () => {
    state.locale=locale;
    const html=renderToStaticMarkup(<StaffEditor data={workspace} member={{subject_id:'زميل Latin 😀 <private>',revision:3,state:'active',ordinary:true,permissions:[]}} refresh={vi.fn()} />);
    expect(html).toContain('زميل Latin 😀 &lt;private&gt;');
  });
});
it('keeps both translation dictionaries complete and identical in shape', () => {
  expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort());
  expect(Object.values(ar).every(value=>value.trim().length>0)).toBe(true);
});

it.each([0,1,1000])('uses bounded server pages for %i records without losing rows', total => {
  const records = new Set<string>();
  for (let page=1;page<=Math.max(1,Math.ceil(total/25));page++) {
    const answer = staffWorkspaceFixture(page,total);
    expect(answer.total).toBe(total);
    expect(answer.items.length).toBeLessThanOrEqual(25);
    answer.items.forEach(item => records.add(item.subject_id));
  }
  expect(records.size).toBe(total);
});
