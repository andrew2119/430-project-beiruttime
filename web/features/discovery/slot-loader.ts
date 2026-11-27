import type { ComponentType } from 'react';
import type { SlotContext } from '@/registry-types';
export type LoadedSlot = {id:string;component:ComponentType<SlotContext>|null};
export async function loadWatchSlots(entries: {id:string;load:()=>Promise<{default:ComponentType<SlotContext>}>}[]): Promise<LoadedSlot[]> {
  return Promise.all(entries.map(async slot=>{
    try{return {id:slot.id,component:(await slot.load()).default};}
    catch{return {id:slot.id,component:null};}
  }));
}
export function slotMountKey(id:string,accessFingerprint:string|null): string {
  return `${id}:${accessFingerprint??'public'}`;
}
