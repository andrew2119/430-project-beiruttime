import { authenticatedRequest } from '@/features/identity/session';
import type { Device, PushCommand, PushResult } from '@contracts/contracts-comms/browser-push';
const base = '/api/web/v1/communications/v1/browser-push';
export async function deviceRead(device:string,scope:string,signal:AbortSignal) {
  return authenticatedRequest<Device>(`${base}/devices/${device}`,{signal,accessFingerprint:scope});
}
export async function submit(body:PushCommand,scope:string):Promise<PushResult> {
  return authenticatedRequest<PushResult>(`${base}/devices`,{method:'POST',accessFingerprint:scope,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
export async function existingRegistration():Promise<ServiceWorkerRegistration> {
  if (!isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) throw new Error('unavailable');
  const registration = await navigator.serviceWorker.getRegistration('/');
  if (!registration?.active) throw new Error('unavailable');
  return registration;
}
export function installation():string {
  const key='bt-push-device-v1';
  const stored=localStorage.getItem(key);
  if (stored && /^[0-9a-f-]{36}$/.test(stored)) return stored;
  const value=crypto.randomUUID(); localStorage.setItem(key,value); return value;
}
