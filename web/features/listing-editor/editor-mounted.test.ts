import { act, createElement, type ChangeEvent, type ComponentProps, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Listing } from "@contracts/contracts-catalog/listings/v1";
import { LocaleContext } from "@/shell/locale-context";
import { ApiError } from "@/lib/api/client";
import { descendants, mountedHost, type HostNode } from "./mounted-dom";
import { copy } from "./copy";

const state = vi.hoisted(() => ({
  read: vi.fn(), save: vi.fn(), upload: vi.fn(), publish: vi.fn(),
  tabs: null as null | {onChange: (value: string) => void; value: string},
  inputs: [] as ComponentProps<"input">[],
}));
vi.mock("next/navigation", () => ({useSearchParams: () => new URLSearchParams()}));
vi.mock("@/shell/access-context", () => ({useAccessContext: () => ({fingerprint: "owner"})}));
vi.mock("@/features/identity/session", () => ({useSession: () => null}));
vi.mock("@tanstack/react-query", () => ({useQuery: ({queryKey}: {queryKey: string[]}) => ({
  data: queryKey[0] === "listing-editor" ? state.read() : {items: []}, dataUpdatedAt: 1,
})}));
vi.mock("./api", () => ({listingApiFor: () => state, scopedHref: (path: string) => path}));
vi.mock("./components", () => ({Failure: ({retry, t}: {retry?: () => void; t: ReturnType<typeof copy>}) => retry ? createElement("button", {onClick: retry}, t.retry) : null, OwnerPhoto: () => null, Status: () => null}));
vi.mock("@/shell/page-header", () => ({
  PageLayout: ({children}: {children: ReactNode}) => children,
  PageHeader: ({nav}: {nav: ReactNode}) => nav,
}));
vi.mock("@beirut-time/ui", () => ({
  Button: (props: ComponentProps<"button">) => createElement("button", props),
  ButtonLink: ({children, href}: {children: ReactNode; href: string}) => createElement("a", {href}, children),
  Card: ({children}: {children: ReactNode}) => createElement("section", null, children),
  Input: (props: ComponentProps<"input">) => {state.inputs.push(props); return createElement("input", props);},
  Textarea: (props: ComponentProps<"textarea">) => createElement("textarea", props),
  Checkbox: ({children, ...props}: ComponentProps<"input">) => createElement("label", null, createElement("input", {...props, type: "checkbox"}), children),
  BidiReference: ({children}: {children: ReactNode}) => children,
  Skeleton: () => null, Select: () => null,
  HeaderTabs: (props: NonNullable<typeof state.tabs>) => {state.tabs = props; return null;},
}));
import Editor from "./editor";

let root: Root;
let container: HostNode;
const initial: Listing = {
  id: "listing", revision: 1, status: "draft", seller_type: "private", seller_label: "Seller",
  physical_watch_id: "watch", is_demo: true, is_hidden: false, photo_ids: [], cover_id: null,
  published_at: null, updated_at: "2026-11-16T00:00:00Z", rules_version: null, fee_snapshot: null,
  facts: {brand: "Sample", model: "Watch", reference: "Reference", year: 2020,
    condition: "Wear", component_wear: {}, location: "Beirut", included: [], no_documents: true,
    modified: false, modifications: [], ownership_confirmed: true, sale_mode: "fixed_price",
    currency: "USD", price_minor: 500000},
};
async function render(locale: "en" | "ar") {
  state.inputs = [];
  await act(async () => root.render(createElement(LocaleContext.Provider, {value: locale}, createElement(Editor, {id: "listing"}))));
}
function files() { return descendants(container).filter(node => node.tagName === "INPUT" && props(node).type === "file"); }
function props(node: HostNode): Record<string, unknown> {
  const key = Object.keys(node).find(key => key.startsWith("__reactProps$"))!;
  return (node as unknown as Record<string, Record<string, unknown>>)[key] ?? {};
}
async function select(file: File) {
  const onChange = props(files()[1]).onChange as (event: {target: {files: File[]; value: string}}) => void;
  await act(async () => onChange({target: {files: [file], value: file.name}}));
}
async function click(label: string) {
  const node = descendants(container).find(node => node.tagName === "BUTTON" && props(node).children === label)!;
  await act(async () => (props(node).onClick as () => void)());
}
beforeEach(() => {
  const host = mountedHost();
  vi.stubGlobal("document", host.document);
  vi.stubGlobal("window", host.window);
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = host.container;
  root = createRoot(container as unknown as HTMLElement);
  state.read.mockReset().mockReturnValue(initial);
  state.save.mockReset().mockImplementation(async (_row, facts) => ({...initial, revision: 2, facts}));
  state.upload.mockReset();
  state.publish.mockReset();
});
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals(); });

it.each(["stale_revision", "listing_frozen"])("locks both selections until current-version review after %s", async code => {
  state.upload.mockRejectedValue(new ApiError(409, code, ""));
  await render("en");
  await act(async () => state.tabs!.onChange("2"));
  const safety = descendants(container).find(node => node.tagName === "INPUT" && props(node).type === "checkbox")!;
  await act(async () => (props(safety).onChange as (event: {target: {checked: boolean}}) => void)({target: {checked: true}}));
  expect(files().map(node => props(node).disabled)).toEqual([false, false]);
  const file = new File(["private"], "proof.pdf");
  await select(file);
  expect(files().map(node => props(node).disabled)).toEqual([true, true]);
  await render("ar");
  expect(state.tabs!.value).toBe("2");
  expect(files().map(node => props(node).disabled)).toEqual([true, true]);
  state.read.mockReturnValue({...initial, revision: 3});
  await click(copy("ar").reviewCurrent);
  expect(props(files()[1]).disabled).toBe(false);
  state.upload.mockResolvedValue({listing: {...initial, revision: 4}});
  await click(copy("ar").retry);
  expect(state.upload.mock.calls[1][1]).toBe(file);
  expect(state.upload.mock.calls[1][0].revision).toBe(3);
});

it("keeps dirty facts, step, private file and uncertain reference through in-place language changes", async () => {
  state.upload.mockRejectedValue(new TypeError("lost response"));
  await render("en");
  const mixed = "ساعة Reference ⌚";
  await act(async () => state.inputs.find(input => input.value === "Sample")!.onChange!({target: {value: mixed}} as ChangeEvent<HTMLInputElement>));
  await render("ar");
  expect(state.inputs.some(input => input.value === mixed)).toBe(true);
  expect(state.save).not.toHaveBeenCalled();
  await act(async () => state.tabs!.onChange("2"));
  const file = new File(["private bytes"], "إثبات.pdf");
  await select(file);
  const original = state.upload.mock.calls[0];
  expect(state.save.mock.calls[0][1].brand).toBe(mixed);
  await render("en");
  expect(state.tabs!.value).toBe("2");
  expect(state.upload).toHaveBeenCalledTimes(1);
  expect(state.save).toHaveBeenCalledTimes(1);
  await click(copy("en").retry);
  expect(state.upload.mock.calls[1]).toEqual(original);
  expect(state.upload.mock.calls[1][1]).toBe(file);
  await act(async () => state.tabs!.onChange("0"));
  expect(state.inputs.some(input => input.value === mixed)).toBe(true);
});

it("reviews the current version before retrying stale dirty facts", async () => {
  state.save.mockRejectedValueOnce(new ApiError(409, "stale_revision", ""));
  await render("en");
  const mixed = "ساعة Changed ⌚";
  await act(async () => state.inputs.find(input => input.value === "Sample")!.onChange!({target: {value: mixed}} as ChangeEvent<HTMLInputElement>));
  await click(copy("en").save);
  expect(state.save.mock.calls[0][0].revision).toBe(1);
  await render("ar");
  state.read.mockReturnValue({...initial, revision: 3, facts: {...initial.facts, brand: "Current"}});
  await click(copy("ar").reviewCurrent);
  expect(state.save).toHaveBeenCalledTimes(1);
  expect(state.inputs.some(input => input.value === mixed)).toBe(true);
  await click(copy("ar").keepChanges);
  await click(copy("ar").save);
  expect(state.save.mock.calls[1][0].revision).toBe(3);
  expect(state.save.mock.calls[1][1].brand).toBe(mixed);
});


it.each(["pending", "lost_response"])("retries the retained publication after preflight %s across a language change", async outcome => {
  const quote = {id: "test-quote", price_minor: 500000, currency: "USD", seller_fee_minor: 25000, buyer_fee_minor: 15000};
  const draft = {...initial, fee_snapshot: quote};
  state.read.mockReturnValue(draft);
  state.publish.mockRejectedValueOnce(outcome === "pending"
    ? new ApiError(503, "publication_review_pending", "") : new TypeError("lost response"));
  state.publish.mockResolvedValueOnce({...draft, status: "published", revision: 2});
  await render("en");
  await act(async () => state.tabs!.onChange("3"));
  const button = descendants(container).find(node => node.tagName === "BUTTON" &&
    (props(node).children as unknown[])?.includes?.(copy("en").publish))!;
  await act(async () => (props(button).onClick as () => void)());
  expect(state.publish).toHaveBeenCalledTimes(1);
  const original = state.publish.mock.calls[0];
  expect(original[0]).toBe(draft);
  expect(original[1]).toBe(quote);
  expect(original[2]).toEqual(expect.any(String));
  await render("ar");
  state.read.mockClear();
  expect(state.tabs!.value).toBe("3");
  await click(copy("ar").retry);
  expect(state.publish).toHaveBeenCalledTimes(2);
  expect(state.publish.mock.calls[1]).toEqual(original);
  expect(state.publish.mock.calls[1][0]).toBe(original[0]);
  expect(state.publish.mock.calls[1][1]).toBe(original[1]);
  expect(state.read).not.toHaveBeenCalled();
});


it.each([
  ["en", "private"], ["ar", "private"], ["en", "dealer"], ["ar", "dealer"],
  ["en", "brand"], ["ar", "brand"],
] as const)("shows applicable terms and support before publication in %s for %s", async (locale, sellerType) => {
  state.read.mockReturnValue({...initial, seller_type: sellerType});
  await render(locale);
  await act(async () => state.tabs!.onChange("3"));
  const t = copy(locale);
  const nodes = descendants(container);
  for (const text of [t.publicationTerms, t.feeTerms, t.returnTerms, sellerType === "private" ? t.privateAssuranceTerms : t.businessAssuranceTerms]) {
    expect(nodes.some(node => props(node)?.children === text)).toBe(true);
  }
  expect(nodes.some(node => props(node)?.children === (sellerType === "private" ? t.businessAssuranceTerms : t.privateAssuranceTerms))).toBe(false);
  const support = nodes.find(node => node.tagName === "A" && props(node)?.children === t.publicationSupport)!;
  expect(props(support).href).toBe(`/${locale}/inbox`);
  const publish = nodes.find(node => node.tagName === "BUTTON" &&
    (props(node)?.children as unknown[])?.includes?.(t.publish))!;
  expect(nodes.indexOf(support)).toBeLessThan(nodes.indexOf(publish));
  expect(state.publish).not.toHaveBeenCalled();
});
