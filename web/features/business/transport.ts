"use client";
import { request, requestBlob, ApiError } from "@/lib/api/client";
import {
  authenticatedRequest,
  refreshSession,
} from "@/features/identity/session";

export async function businessRequest<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const invoke = authenticated ? authenticatedRequest : request;
  return invoke<T>(`/api/web/v1/identity${path}`, { ...options, headers });
}
const uncertain = new Map<string, string>();
let accessGeneration = 0;
if (typeof window !== "undefined")
  window.addEventListener("bt:access-change", () => {
    accessGeneration++;
    uncertain.clear();
  });
export async function businessFile(path: string, token: string | null) {
  const expected = accessGeneration;
  let currentToken = token;
  const invoke = async () => {
    currentToken ??= (await refreshSession())?.access_token ?? null;
    if (!currentToken) throw new ApiError(401, "unauthorized", "");
    return requestBlob(`/api/web/v1/identity${path}`, {
      headers: { Authorization: `Bearer ${currentToken}` },
    });
  };
  let blob: Blob;
  try {
    blob = await invoke();
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    currentToken = (await refreshSession())?.access_token ?? null;
    blob = await invoke();
  }
  if (expected !== accessGeneration)
    throw new ApiError(401, "unauthorized", "");
  return blob;
}
export async function command<T>(path: string, body: unknown, method = "POST") {
  const json = JSON.stringify(body);
  const fingerprintJson =
    path === "/v1/contacts/challenges" &&
    body !== null &&
    typeof body === "object"
      ? JSON.stringify({ ...body, proof: undefined })
      : json;
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(method + path + fingerprintJson),
  );
  const fingerprint = Array.from(new Uint8Array(bytes), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  // An uncertain retry reuses one key, never doubles an effect.
  const operation = uncertain.get(fingerprint) ?? crypto.randomUUID();
  uncertain.set(fingerprint, operation);
  try {
    const result = await businessRequest<T>(path, {
      method,
      headers: { "Idempotency-Key": operation },
      body: json,
    });
    uncertain.delete(fingerprint);
    return result;
  } catch (error) {
    if (error instanceof ApiError && error.status < 500 && error.status !== 429)
      uncertain.delete(fingerprint);
    throw error;
  }
}
