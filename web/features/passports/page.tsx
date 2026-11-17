'use client';
import { usePageRead } from '@/lib/page-speed/read';
import { AnswerArrival } from '@/lib/page-speed/arrival';
import { passportRead } from './reads';
import { PassportView } from './view';


export function PassportPage({id}:{id:string}) {
  const query = usePageRead(passportRead(id));
  const answer = query.data ?? {state:query.isError ? 'unavailable' : 'loading'};
  const view = <PassportView answer={answer} retry={()=>{void query.refetch();}}/>;
  return query.data === undefined ? view : <AnswerArrival view={`passports:${id}`}>{view}</AnswerArrival>;
}
