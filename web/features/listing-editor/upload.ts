import { ApiError } from "@/lib/api/client";
import type { Listing } from "@contracts/contracts-catalog/listings/v1";

export type UploadCommand = {
  listing: Listing;
  file: File;
  kind: "public_photo" | "private_document";
  key: string;
};

export class RetainedUpload {
  command: UploadCommand | null = null;

  async send<T>(proposed: UploadCommand, transport: (command: UploadCommand) => Promise<T>, safe = false): Promise<T> {
    if (!this.command && proposed.kind === "public_photo" && !safe)
      throw new ApiError(422, "safe_photo_required", "");
    const command = this.command ?? proposed;
    if (command.file !== proposed.file || command.kind !== proposed.kind)
      throw new ApiError(409, "upload_pending", "");
    this.command = command;
    try {
      const result = await transport(command);
      this.command = null;
      return result;
    } catch (error) {
      const correctable = ["stale_revision", "listing_frozen", "invalid_image", "media_bytes_limit", "empty_media", "safe_photo_required", "media_aggregate_limit"];
      if (error instanceof ApiError && correctable.includes(error.code)) this.command = null;
      throw error;
    }
  }
}
