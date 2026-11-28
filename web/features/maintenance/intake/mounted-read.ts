'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PageRead } from '@/lib/page-speed/definition';
import { privateRecordUnavailable } from '../private-read';

type Answer<T> = { data?: T; error?: unknown };
export type IntakeRead = <T>(read: PageRead<T> | null) => Answer<T> & {
  isPending: boolean;
  isFetching: boolean;
  isPaused: boolean;
  refetch: () => unknown;
};

/** Bridge for the older shell. Answers live only in the mounted editor. */
export const useMountedIntakeRead: IntakeRead = <T,>(read: PageRead<T> | null) => {
  const key = read ? JSON.stringify(read.key) : null;
  const latest = useRef(read);
  useEffect(() => { latest.current = read; }, [read]);
  const [attempt, setAttempt] = useState(0);
  const [answer, setAnswer] = useState<Answer<T> & {key: string; attempt: number}>();
  const refetch = useCallback(() => setAttempt(value => value + 1), []);

  useEffect(() => {
    if (!key || !latest.current) return;
    const controller = new AbortController();
    latest.current.ask(controller.signal).then(
      data => {
        if (!controller.signal.aborted) setAnswer({key, attempt, data});
      },
      error => {
        if (!controller.signal.aborted) setAnswer(previous => ({
          key, attempt, error,
          data: previous?.key === key && !privateRecordUnavailable(error) ? previous.data : undefined,
        }));
      },
    );
    return () => controller.abort();
  }, [key, attempt]);

  const current = key !== null && answer?.key === key ? answer : undefined;
  const isFetching = key !== null && current?.attempt !== attempt;
  return {data: current?.data, error: current?.error, isPending: isFetching && !current?.data,
    isFetching, isPaused: false, refetch};
};
