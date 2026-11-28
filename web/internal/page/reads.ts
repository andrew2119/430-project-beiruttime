import { request } from '@/lib/api/client';
import { definePageRead } from '@/lib/page-speed/definition';
import { reviewMode, PAGE_SIZE } from '@/internal/components/model';
import type { ReviewDataMode } from '@/tests/fixtures/worst-case';
export type DemoRequest = {mode:ReviewDataMode;page:number};
export type DemoAnswer = {items:{id:string;title:string;reference:string}[];total:number;page:number;pages:number;servedAt:number};
export function demoRequest(mode:unknown,page:unknown):DemoRequest {const number = typeof page === 'string' && /^\d{1,3}$/.test(page) ? Number(page) : 0;return {mode:reviewMode(mode),page:Math.min(83,Math.max(0,number))};}
export const demoRead = definePageRead({key:({mode,page}:DemoRequest)=>['page-demo',mode,page],warm:'safe',ask:async(signal,{mode,page}:DemoRequest):Promise<DemoAnswer>=>{
  const answer = await request<unknown>(`/api/internal/page-data?data=${mode}&page=${page}`,{signal});
  if (!answer || typeof answer !== 'object') throw new Error('Invalid review records');
  const value = answer as DemoAnswer;
  if (!Array.isArray(value.items) || value.items.length > PAGE_SIZE || value.items.some(item=>!item || typeof item.id !== 'string' || typeof item.title !== 'string' || typeof item.reference !== 'string') || !Number.isSafeInteger(value.total) || value.total < 0 || value.total > 1000 || !Number.isSafeInteger(value.page) || value.page < 0 || !Number.isSafeInteger(value.pages) || value.pages < 1 || value.page >= value.pages || !Number.isSafeInteger(value.servedAt)) throw new Error('Invalid review records');
  return value;
}});
