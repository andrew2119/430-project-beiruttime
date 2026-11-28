'use client';

import { skipToken, useQuery } from '@tanstack/react-query';
import { ANSWER_HELD_MS } from './policy';
import { usePageReadScope } from './provider';
import type { ReadScope } from './scope';
import { keptPageAnswer, optionsFor, type PageRead } from './definition';
/** Held data is drawn during refresh. Changed filters may keep only the exact
 * preceding cache entry while it still belongs to this live access scope. */
export function usePageRead<T>(read:PageRead<T>|null,{keep=false}:{keep?:boolean} = {}) {
  const scope = usePageReadScope(), options = read ? optionsFor(scope,read) : null;
  return useQuery<T>({queryKey:options?.queryKey ?? ['bt-page',scope.key,'none'],queryFn:options?.queryFn ?? skipToken,staleTime:options?.staleTime,gcTime:ANSWER_HELD_MS,retry:false,
    placeholderData:keep ? (answer,previous)=>keptPageAnswer(scope,answer,previous) : undefined});
}
export function refreshPageReads(scope:ReadScope) {if (scope.valid()) void scope.client.refetchQueries({type:'active',stale:true},{cancelRefetch:false});}
