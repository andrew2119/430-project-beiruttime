"use client";
import { useCallback, useEffect, useRef } from "react";
import { readNonSecretDraft, saveNonSecretDraft } from "@/shell/private-state";

/** Only public presentation choices survive a locale switch. Never persist the
 * legal identity, assurance reference, reason, credentials or verification code. */
export function usePublicBusinessDraft(owner: string | null) {
  const form = useRef<HTMLFormElement | null>(null);
  const attachForm = useCallback((node: HTMLFormElement | null) => {
    form.current = node;
  }, []);
  useEffect(() => {
    if (!owner || !form.current) return;
    try {
      const value = readNonSecretDraft(owner, "business-onboard");
      if (!value) return;
      const draft = JSON.parse(value) as {
        public_name?: unknown;
        kind?: unknown;
        capabilities?: unknown;
        sample?: unknown;
      };
      const name = form.current.elements.namedItem("public_name");
      const kind = form.current.elements.namedItem("kind");
      if (
        name instanceof HTMLInputElement &&
        typeof draft.public_name === "string" &&
        draft.public_name.length <= 120
      )
        name.value = draft.public_name;
      if (
        kind instanceof HTMLSelectElement &&
        (draft.kind === "brand" || draft.kind === "dealer")
      ) {
        kind.value = draft.kind;
        // Update the menu bridge without re-saving a half-restored form through
        // the parent's autosave while capabilities are still being restored.
        kind.dispatchEvent(new Event("change"));
      }
      form.current
        .querySelectorAll<HTMLInputElement>('input[name="capabilities"]')
        .forEach((input) => {
          if (Array.isArray(draft.capabilities))
            input.checked = draft.capabilities.includes(input.value);
        });
      const sample = form.current.elements.namedItem("sample");
      if (
        sample instanceof HTMLInputElement &&
        typeof draft.sample === "boolean"
      )
        sample.checked = draft.sample;
    } catch {
      /* Storage is a convenience, never business authority. */
    }
  }, [owner]);
  const save = useCallback(() => {
    if (!owner || !form.current) return;
    const data = new FormData(form.current);
    try {
      saveNonSecretDraft(
        owner,
        "business-onboard",
        JSON.stringify({
          public_name: String(data.get("public_name") ?? ""),
          kind: String(data.get("kind") ?? ""),
          capabilities: data.getAll("capabilities"),
          sample: data.get("sample") === "on",
        }),
      );
    } catch {
      /* Restricted storage must not block a command. */
    }
  }, [owner]);
  const clear = useCallback(() => {
    if (owner)
      try {
        saveNonSecretDraft(owner, "business-onboard", "{}");
      } catch {
        /* Optional draft only. */
      }
  }, [owner]);
  return { attachForm, save, clear };
}
