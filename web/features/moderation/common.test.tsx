import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
const access = vi.hoisted(() => ({ roles: [] as string[] }));
vi.mock("@/shell/locale-context", () => ({ useLocale: () => "ar" }));
vi.mock("@/features/identity/session", () => ({ useSession: () => ({ principal: { roles: access.roles } }) }));
vi.mock("next/navigation", () => ({ usePathname: () => "/ar/operations/dashboard", useRouter: () => ({ push: vi.fn() }) }));
import { ApiError } from "@/lib/api/client";
import { ErrorNotice, FeatureFrame, LoadState } from "./common";

describe("operations shared-kit states", () => {
  beforeEach(() => { access.roles = []; });
  it("announces loading once while reserving the coming rows", () => {
    const html = renderToStaticMarkup(<LoadState loading refresh={() => {}}/>);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('role="status"');
    expect(html.match(/ops-row-skeleton/g)).toHaveLength(3);
  });
  it("uses a calm empty face rather than inventing queue records", () => {
    const html = renderToStaticMarkup(<LoadState loading={false} empty refresh={() => {}}/>);
    expect(html).toContain('pg-face');
    expect(html).not.toContain('ops-records');
  });
  it("keeps locale-aware sign-in links and the original authorization message", () => {
    const html = renderToStaticMarkup(<ErrorNotice error={new ApiError(401, "unauthorized", "sample-reference")}/>);
    expect(html).toContain('href="/ar/account"');
    expect(html).toContain('pg-face');
  });
  it("preserves support references and a real retry button for failed loads", () => {
    const html = renderToStaticMarkup(<ErrorNotice error={new ApiError(503, "unavailable", "sample-reference")} retry={() => {}}/>);
    expect(html).toContain('role="alert"');
    expect(html).toContain('sample-reference');
    expect(html).toContain('type="button"');
  });
  it("only advertises role-appropriate operation tabs", () => {
    access.roles = ["dealer"];
    const html = renderToStaticMarkup(<FeatureFrame title="intake" intro="intakeIntro"><p>Records</p></FeatureFrame>);
    expect(html).toContain('href="/ar/business-intake"');
    expect(html).not.toContain('href="/ar/operations/moderation"');
    expect(html).not.toContain('href="/ar/operations/dashboard"');
    expect(html).toContain('hx-head');
  });
});
