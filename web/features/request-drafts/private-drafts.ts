import { draftMemoryEpoch } from './memory';
import { ApiError } from '../../lib/api/client';

export function privateAccessDenied(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export async function readPrivateDrafts<T>(read: () => Promise<T>, revoke: () => void): Promise<T> {
  const generation = draftMemoryEpoch();
  try {
    return await read();
  } catch (error) {
    if (privateAccessDenied(error) && draftMemoryEpoch() === generation) revoke();
    throw error;
  }
}
