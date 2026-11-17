import { ApiError } from '@/lib/api/client';
/** One unresolved operation retains its exact request until confirmed. */
export class InboxRecovery {
  current: (()=>Promise<void>) | null = null;
  busy = false;
  async run(action:()=>Promise<void>):Promise<'confirmed'|'refused'|'uncertain'|'blocked'> {
    if(this.busy||(this.current&&this.current!==action))return 'blocked';
    this.busy=true;
    this.current=action;
    try {await action();this.current=null;return 'confirmed';}
    catch(error) {
      if(error instanceof ApiError&&[400,401,403,404,409,410,422].includes(error.status)) {
        this.current=null;
        return 'refused';
      }
      return 'uncertain';
    }
    finally {this.busy=false;}
  }
}
