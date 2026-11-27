/** Keep the original command until its result is conclusive. */
export function retainCommand<T>(commands:Map<string,T>,id:string,create:()=>T):T {
 const existing=commands.get(id);
 if(existing)return existing;
 const command=create();
 commands.set(id,command);
 return command;
}
