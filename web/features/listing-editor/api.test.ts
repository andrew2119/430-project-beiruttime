import { beforeEach, expect, it, vi } from "vitest";
import type {
  Listing,
  FeeQuote,
} from "@contracts/contracts-catalog/listings/v1";
const { authenticatedRequest, requestBlob, refreshSession } = vi.hoisted(
  () => ({
    authenticatedRequest: vi.fn(),
    requestBlob: vi.fn(),
    refreshSession: vi.fn(),
  }),
);
vi.mock("@/features/identity/session", () => ({
  authenticatedRequest,
  refreshSession,
}));
vi.mock("@/lib/api/client", () => ({
  requestBlob,
  ApiError: class extends Error {},
}));
import { listingApiFor } from "./api";
beforeEach(() => vi.clearAllMocks());
const row = {
  id: "listing-id",
  revision: 7,
  facts: { price_minor: 18000, currency: "USD" },
} as Listing;

it("captures the form owner and selected organization in every mutation", async () => {
  const api = listingApiFor("owner-fingerprint", "selected-org");
  await api.create("create-operation");
  expect(authenticatedRequest).toHaveBeenCalledWith(
    expect.stringContaining("organization_id=selected-org"),
    expect.objectContaining({ accessFingerprint: "owner-fingerprint" }),
  );
  await api.upload(
    row,
    new Blob(["watch"]) as File,
    "public_photo",
    "upload-operation",
  );
  expect(authenticatedRequest).toHaveBeenLastCalledWith(
    expect.stringContaining("&organization_id=selected-org"),
    expect.objectContaining({ accessFingerprint: "owner-fingerprint" }),
  );
});
it("requests the exact sample Pricing contract in personal context", async () => {
  await listingApiFor("owner", "selected-org").quote(row, "quote-operation");
  const [path, options] = authenticatedRequest.mock.calls[0];
  expect(path).toBe("/api/web/v1/pricing/v1/quotes");
  expect(options.accessFingerprint).toBe("owner");
  expect(JSON.parse(options.body)).toEqual({
    subject_id: "listing-id",
    subject_revision: 7,
    purpose: "business_quote",
    source: "sample",
    schedule_id: "sample-v1",
    price_minor: 18000,
    currency: "USD",
  });
});
it("maps the schedule identifier without inventing a quote-valid status", async () => {
  await listingApiFor("owner", null).publish(
    row,
    { id: "quote-id", schedule_id: "sample-v1" } as FeeQuote,
    "publish-operation",
  );
  const [, options] = authenticatedRequest.mock.calls[0];
  expect(JSON.parse(options.body)).toEqual({
    fee_quote_id: "quote-id",
    rules_version: "sample-v1",
  });
});
