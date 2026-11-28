import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import type { ComponentProps } from 'react';
import type { StaffWorkspace } from '@contracts/contracts-identity/businesses/workspace_v2';
import type { CommandForm } from './command-form';

const capture = vi.hoisted(() => ({ submit: null as ComponentProps<typeof CommandForm>['submit'] | null }));
vi.mock('./command-form', () => ({ CommandForm: (props: ComponentProps<typeof CommandForm>) => {
  capture.submit = props.submit;
  return props.children;
} }));
vi.mock('@/shell/locale-context', () => ({ useLocale: () => 'en' }));
import { StaffEditor } from './membership';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const workspace: StaffWorkspace = {
  organization_id: 'business', actor_id: 'administrator', can_manage: true,
  ceiling_revision: 2, ceiling: ['business.records.read'], responsibilities_current: true,
  jobs: [{ job_id: 'job', responsible_id: 'colleague', revision: 4 }],
  replacements: [{ subject_id: 'replacement', revision: 1 }],
  items: [], page: 1, page_size: 25, total: 1,
};
const policy = `
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('staff_policy', Path('services/identity/modules/membership/administration.py'))
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)
body = json.loads(sys.argv[1])
authority = s.Administration(s.Member(body['actor_id'], body['organization_id'], frozenset({'business.staff.manage'})), body['organization_id'], True, frozenset({'business.records.read'}), body['ceiling_revision'])
member = s.Member(body['subject_id'], body['organization_id'], frozenset({'business.stock.write', 'business.jobs.write', 'business.records.read'}), 3)
replacement = s.Member('replacement', body['organization_id'], frozenset({'business.jobs.write'})) if body['replacement_id'] else None
try:
    result = s.change(authority, member.subject_id, member.business_id, body['expected_revision'], body['kind'], body['permissions'], body['reason'], existing=member, jobs=(s.Job('job', member.business_id, member.subject_id, body['job_revisions']['job']),), replacement=replacement, responsibilities_current=True)
    print(json.dumps({'state': result.member.state, 'permissions': sorted(result.member.permissions), 'responsible_id': result.jobs[0].responsible_id, 'revision': result.jobs[0].revision}))
except s.AdministrationDenied as error:
    print(json.dumps({'denied': str(error)}))
`;

it.each(['grant', 'suspend', 'remove'] as const)('submits a lowered-ceiling %s from the form through the policy with replacement', async kind => {
  renderToStaticMarkup(<StaffEditor data={workspace} member={{ subject_id: 'colleague', revision: 3, state: 'active', ordinary: true,
    permissions: ['business.stock.write', 'business.jobs.write', 'business.records.read'] }} refresh={vi.fn()} />);
  const form = new FormData();
  form.set('kind', kind); form.set('reason', 'Current ordinary staff change'); form.set('replacement', 'replacement');
  const send = vi.fn().mockResolvedValue({});
  await capture.submit!(form, { send } as unknown as Parameters<NonNullable<typeof capture.submit>>[1]);
  const [path, body] = send.mock.calls[0];
  expect(path).toBe('/v2/business-staff/commands');
  expect(body.permissions).toEqual(['business.records.read']);
  expect(body).toMatchObject({ expected_revision: 3, ceiling_revision: 2, job_revisions: { job: 4 }, replacement_revision: 1 });
  const apply = async (request: typeof body) => JSON.parse((await promisify(execFile)('python3', ['-c', policy, JSON.stringify(request)], { cwd: root, encoding: 'utf8', timeout: 5000 })).stdout);
  expect(await apply(body)).toMatchObject({ state: { grant: 'active', suspend: 'suspended', remove: 'revoked' }[kind], responsible_id: 'replacement', revision: 5 });
  if (kind === 'grant') expect((await apply(body)).permissions).toEqual(['business.records.read']);
  expect(await apply({ ...body, replacement_id: null })).toEqual({ denied: 'responsible_replacement_required' });
});
