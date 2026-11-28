/** Access denial clears private answers; uncertain delivery keeps its reference. */
export function failureRecovery<T>(status:number|null,lookup:boolean,outcome:T|null,unresolved=false){
 const denied=status!==null&&[401,403,409,422].includes(status);
 return {
  outcome:status===401||status===403?null:outcome,
  error:denied?'denied' as const:'unavailable' as const,
  rejected:!lookup&&denied&&!unresolved,
 };
}
