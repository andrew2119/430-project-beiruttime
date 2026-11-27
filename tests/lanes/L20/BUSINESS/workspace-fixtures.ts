import type { StaffWorkspace } from '../../../../packages/contracts-identity/businesses/workspace_v2';
/** Synthetic read-only fixture. It grants no connected authority. */
export function staffWorkspaceFixture(page: number, total: number): StaffWorkspace {
  const page_size = 25;
  return {
    organization_id:'00000000-0000-0000-0000-000000000005',
    actor_id:'00000000-0000-0000-0000-000000000006',
    page,page_size,total,can_manage:true,ceiling_revision:2,
    ceiling:['business.records.read'],responsibilities_current:true,
    jobs:[],replacements:[],
    items:Array.from({length:Math.max(0,Math.min(page_size,total-(page-1)*page_size))},(_,offset) => ({
      subject_id:`00000000-0000-0000-0000-${String((page-1)*page_size+offset+100).padStart(12,'0')}`,
      revision:1,state:'active' as const,ordinary:true,permissions:['business.records.read'],
    })),
  };
}
