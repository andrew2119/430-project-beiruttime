'use client';
import {useQueryClient} from '@tanstack/react-query';
import {recipientRead,type RecipientScope} from './read';

// Compatibility boundary until the shared page composition is available.
export {PageLayout as PageFrame} from '@/shell/page-header';
export function usePageRead(scope:RecipientScope|null){
 return {cache:useQueryClient(),read:scope?recipientRead(scope):null};
}
