'use client';
import { usePageRead } from '@/lib/page-speed/read';
import type { PageRead } from '@/lib/page-speed/definition';

export function privateRecordUnavailable(error: unknown) {
  return typeof error === 'object' && error !== null && 'status' in error &&
    (error.status === 401 || error.status === 403 || error.status === 404);
}

export function usePrivateRead<T>(read:PageRead<T>|null) {
  const answer=usePageRead(read);
  const denied=privateRecordUnavailable(answer.error);
  return {...answer,data:read&&!denied?answer.data:undefined};
}
