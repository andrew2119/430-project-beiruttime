import type { AuditQuery, Outcome } from '@contracts/contracts-comms/audit-references';
export type Filters = {organization:string;actor:string;resource:string;outcome:string;after:string;before:string;operation:string};
export const emptyFilters:Filters = {organization:'',actor:'',resource:'',outcome:'',after:'',before:'',operation:''};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const instant = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;
export function queryFrom(filters:Filters):AuditQuery|null {
  const {organization,actor,resource,outcome,after,before,operation} = filters;
  if (![organization,operation].every(id=>uuid.test(id)) || [actor,resource].some(id=>id!==''&&!uuid.test(id)) ||
    ![after,before].every(value=>instant.test(value)&&Number.isFinite(Date.parse(value))) ||
    Date.parse(before)<=Date.parse(after) || Date.parse(before)-Date.parse(after)>31*86400000 ||
    !['','accepted','denied','pending','cancelled'].includes(outcome)) return null;
  return {schema_version:'audit-references.v1',operation_id:operation,organization_id:organization,
    ...(actor?{actor_id:actor}:{}),...(resource?{resource_id:resource}:{}),...(outcome?{outcome:outcome as Outcome}:{}),
    after,before,offset:0,limit:20};
}
