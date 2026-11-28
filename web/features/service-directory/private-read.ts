import { ApiError } from '@/lib/api/client';

export function privateReadDenied(error: unknown): boolean {
  return error instanceof ApiError && ([401, 403, 404].includes(error.status) || error.code === 'not_official');
}
