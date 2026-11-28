import { describe, expect, it } from "vitest";
import type { Listing } from "@contracts/contracts-catalog/listings/v1";
import { ApiError } from "@/lib/api/client";
import { RetainedUpload, type UploadCommand } from "./upload";

const first = (): UploadCommand => ({listing: {id:"listing",revision:1} as Listing, file: new Blob(["synthetic private file"]) as File, kind:"private_document", key:"original-operation"});

describe("private upload recovery", () => {
  it("retries a lost response with the original file, revision and operation after other screen changes", async () => {
    const retained = new RetainedUpload(), command = first();
    await expect(retained.send(command, async () => {throw new TypeError("lost response");})).rejects.toThrow();
    const changed = {...command, listing:{...command.listing,revision:2},key:"replacement"};
    const result = await retained.send(changed, async actual => {
      expect(actual).toBe(command);
      return {asset_id:"one-asset"};
    });
    expect(result.asset_id).toBe("one-asset");
    expect(retained.command).toBeNull();
  });
  it("retains uncertain commands and refuses to substitute private bytes", async () => {
    const retained = new RetainedUpload(), command = first();
    await expect(retained.send(command, async () => {throw new ApiError(503,"unavailable","");})).rejects.toThrow();
    await expect(retained.send(first(), async () => {throw new Error("must not send");})).rejects.toMatchObject({code:"upload_pending"});
    expect(retained.command).toBe(command);
  });
  it.each([401,403])("keeps a lost response bound after current access denial %s", async status => {
    const retained = new RetainedUpload(), command = first();
    await expect(retained.send(command, async () => {throw new TypeError("lost response");})).rejects.toThrow();
    await expect(retained.send({...command,key:"replacement"}, async () => {throw new ApiError(status,"access_denied","");})).rejects.toThrow();
    expect(retained.command).toBe(command);
    await retained.send({...command,key:"replacement"}, async actual => expect(actual.key).toBe("original-operation"));
  });
  it("allows correction after a definitive file denial", async () => {
    const retained = new RetainedUpload();
    await expect(retained.send(first(), async () => {throw new ApiError(422,"invalid_image","");})).rejects.toThrow();
    expect(retained.command).toBeNull();
  });
});

it('settles a stale upload after retrying the original reference and permits reviewed correction', async () => {
  const retained = new RetainedUpload(), command = first();
  await expect(retained.send(command, async () => { throw new TypeError('lost response'); })).rejects.toThrow();
  await expect(retained.send({...command, key:'replacement'}, async actual => {
    expect(actual).toBe(command);
    throw new ApiError(409,'stale_revision','');
  })).rejects.toMatchObject({code:'stale_revision'});
  expect(retained.command).toBeNull();
  const reviewed = {...command, listing:{...command.listing, revision:2}, key:'reviewed-correction'};
  await retained.send(reviewed, async actual => {
    expect(actual.file).toBe(command.file);
    expect(actual.listing.revision).toBe(2);
    expect(actual.key).toBe('reviewed-correction');
  });
});


it.each([false, true])("settles concurrent publication denial after lost response: %s", async lostResponse => {
  const retained = new RetainedUpload(), command = first();
  if (lostResponse) {
    await expect(retained.send(command, async () => { throw new TypeError("lost response"); })).rejects.toThrow();
  }
  const published = {...command.listing, revision: 2, status: "published"} as Listing;
  await expect(retained.send(lostResponse ? {...command, listing: published, key: "replacement"} : command, async actual => {
    expect(actual).toBe(command);
    throw new ApiError(409, "listing_frozen", "");
  })).rejects.toMatchObject({code: "listing_frozen"});
  expect(retained.command).toBeNull();
  expect(command.file.size).toBeGreaterThan(0);
  const reviewed = {...command, listing: {...published, revision: 3, status: "draft"} as Listing, key: "reviewed-correction"};
  await retained.send(reviewed, async actual => {
    expect(actual.file).toBe(command.file);
    expect(actual.key).toBe("reviewed-correction");
    expect(actual.listing.revision).toBe(3);
  });
});

it("requires a fresh safety declaration after a definitive public-photo denial", async () => {
  const retained = new RetainedUpload(), command = {...first(), kind: "public_photo" as const};
  await expect(retained.send(command, async () => {throw new ApiError(409, "media_aggregate_limit", "");}, true)).rejects.toThrow();
  expect(retained.command).toBeNull();
  let sent = false;
  await expect(retained.send(command, async () => {sent = true;}, false)).rejects.toMatchObject({code: "safe_photo_required"});
  expect(sent).toBe(false);
  expect(retained.command).toBeNull();
  await retained.send({...command, key: "corrected-operation"}, async actual => expect(actual.key).toBe("corrected-operation"), true);
});

it("reconciles an uncertain public photo with its original declaration and reference", async () => {
  const retained = new RetainedUpload(), command = {...first(), kind: "public_photo" as const};
  await expect(retained.send(command, async () => {throw new TypeError("lost response");}, true)).rejects.toThrow();
  await retained.send({...command, key: "replacement"}, async actual => expect(actual).toBe(command), false);
  expect(retained.command).toBeNull();
});
