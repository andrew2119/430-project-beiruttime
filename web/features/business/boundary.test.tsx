import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
const session = vi.hoisted(() => ({ state: "restoring" }));
vi.mock("@/features/identity/session", () => ({
  useSession: () => null,
  useSessionState: () => session.state,
  refreshSession: vi.fn(),
}));
vi.mock("@/shell/access-context", () => ({
  useAccessContext: () => ({ fingerprint: "sample-session" }),
}));
vi.mock("@/shell/locale-context", () => ({ useLocale: () => "ar" }));
vi.mock("./components", () => ({
  useCopy: () => ({ private: "Private", contactIntro: "Private records", loading: "Restoring session", unavailable: "Unavailable", retry: "Retry", signin: "Sign in" }),
  Workspace: ({ children }: { children: ReactNode }) => createElement("section", null, children),
}));
import BusinessBoundary from "./boundary";
function render(publicWorkspace = false) {
  return renderToStaticMarkup(
    <BusinessBoundary publicWorkspace={publicWorkspace}>
      <input name="private-input" />
    </BusinessBoundary>,
  );
}
describe("private form admission", () => {
  beforeEach(() => { session.state = "restoring"; });
  it("does not admit typing before session restoration can remount the form", () => {
    expect(render()).toContain("Restoring session");
    expect(render()).not.toContain("private-input");
  });
  it("keeps public discovery available during restoration", () => {
    expect(render(true)).toContain("private-input");
  });
  it("admits a private form only after authentication settles", () => {
    session.state = "authenticated";
    expect(render()).toContain("private-input");
  });
  it("offers recovery rather than an editable private form during outage", () => {
    session.state = "unavailable";
    expect(render()).toContain("Unavailable");
    expect(render()).toContain("Retry");
    expect(render()).not.toContain("private-input");
  });
  it("uses the current locale for real sign-in", () => {
    session.state = "signed-out";
    expect(render()).toContain('href="/ar/account"');
    expect(render()).not.toContain("private-input");
  });
});
