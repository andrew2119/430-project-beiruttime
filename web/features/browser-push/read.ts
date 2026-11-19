import { definePageRead } from '@/lib/page-speed/definition';
import { deviceRead } from './client';
export const pushDeviceRead = definePageRead({key:(device:string,scope:string)=>['browser-push.v1',scope,device],ask:(signal,device,scope)=>deviceRead(device,scope,signal),warm:'open-only',fresh:0});
