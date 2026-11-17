export type PhotoScope = { actor: string; business: string; thread: string; watch: string; revision: number };
export type PhotoResult = {
  schema_version: 'communications.message-photos.v1'; operation_id: string;
  subject_id: string; watch_id: string; actor_id: string; organization_id: string;
  expected_revision: number; state: 'uploaded' | 'attached' | 'pending'; revision: number;
  pending_reason: string | null; next_actor: string | null; next_review_at: string | null;
  photo?: string;
};
export type PhotoItem = { id: string; width: number; height: number };
export type PhotoPage = { items: PhotoItem[]; total: number; next_offset: number | null };
/** Scope must come from the authenticated conversation boundary, never query authority. */
export interface MessagePhotos {
  upload(file: File, operation: string, signal: AbortSignal): Promise<PhotoResult>;
  attach(photo: string, operation: string, signal: AbortSignal): Promise<PhotoResult>;
  operation(operation: string, signal: AbortSignal): Promise<PhotoResult>;
  list(offset: number, signal: AbortSignal): Promise<PhotoPage>;
  bytes(photo: string, signal: AbortSignal): Promise<Blob>;
}
