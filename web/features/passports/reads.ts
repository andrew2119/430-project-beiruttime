import { definePageRead } from '@/lib/page-speed/definition';
import type { PassportState } from '../../../packages/contracts-trust/passports/v1';
import { passportId, signedDocument } from './read';

export const passportRead = definePageRead({
    key:(id:string)=>['passports.public.v1',id,'verification.v1'], warm:'safe',
    ask:async (signal:AbortSignal,id:string):Promise<PassportState> => {
      if (!passportId.test(id)) return {state:'empty'};
      const controller = new AbortController();
      const cancel = () => controller.abort();
      const combined = typeof AbortSignal.any === 'function'
        ? AbortSignal.any([signal, controller.signal]) : controller.signal;
      if (signal.aborted) cancel();
      else signal.addEventListener('abort', cancel, {once:true});
      const timeout = setTimeout(cancel, 4000);
      try {
        const response = await fetch(`/passports/${id}/read`, {signal:combined,cache:'no-store',credentials:'omit'});
        if (!response.ok) throw new Error('Verification unavailable');
        const answer = await response.json();
        if (answer.state === 'verified') {
          const document = signedDocument(answer.document,id);
          return document ? {state:'verified',document} : {state:'invalid'};
        }
        if (answer.state === 'unavailable') throw new Error('Verification unavailable');
        return {state:['empty','denied','pending','invalid'].includes(answer.state) ? answer.state : 'invalid'};
      } catch { throw new Error('Verification unavailable'); }
      finally {
        clearTimeout(timeout);
        signal.removeEventListener('abort', cancel);
      }
    },
});
