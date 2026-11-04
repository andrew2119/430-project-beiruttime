import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
vi.mock("@/shell/locale-context", () => ({ useLocale: () => "ar" }));
vi.mock("@/features/identity/session", () => ({ useSession: () => null }));
vi.mock("next/navigation", () => ({ usePathname: () => "/ar/business", useRouter: () => ({ push: vi.fn() }) }));
import { FormSelect } from "./form-select";
import { Field, Select, Submit, Workspace } from "./components";

describe("CP form adapters", () => {
  it("keeps a real named native select for FormData and existing draft recovery", () => {
    const html = renderToStaticMarkup(<FormSelect id="kind" name="kind" defaultValue="brand">
      <option value="dealer">Dealer</option><option value="brand">Brand</option>
    </FormSelect>);
    expect(html).toContain('id="kind"');
    expect(html).toContain('class="ui-select"');
    expect(html).toContain('name="kind"');
    expect(html).toMatch(/<option value="brand" selected="">/);
    expect(html).toContain('aria-haspopup="menu"');
    expect(html).toContain('aria-hidden="true"');
    expect(html.match(/id="kind"/g)).toHaveLength(1);
    expect(html.indexOf("<button")).toBeLessThan(html.indexOf("<select"));
  });
  it("retains explicit field labels, password privacy and native validation", () => {
    const html = renderToStaticMarkup(<Field name="reauth" label="كلمة المرور" type="password" minLength={1} maxLength={128}/>);
    expect(html).toContain('name="reauth"');
    expect(html).toContain('type="password"');
    expect(html).toContain('autoComplete="off"');
    expect(html).toContain('minLength="1"');
    expect(html).toContain('maxLength="128"');
    expect(html).toContain('required=""');
    expect(html).toContain('for=');
  });
  it("associates the visible label with the menu trigger rather than a duplicate ID", () => {
    const html = renderToStaticMarkup(<Select name="channel" label="وسيلة التواصل" options={[{value:"email",label:"البريد"},{value:"phone",label:"الهاتف"}]}/>);
    const target = /for="([^"]+)"/.exec(html)?.[1];
    expect(target).toBeTruthy();
    expect(html).toContain(`id="${target}"`);
    expect(html).toContain('name="channel"');
    expect(html).toContain('data-value="email"');
  });
  it("keeps pending submits disabled and announced", () => {
    const html = renderToStaticMarkup(<Submit label="حفظ" pending/>);
    expect(html).toContain('type="submit"');
    expect(html).toContain('disabled=""');
    expect(html).toContain('aria-busy="true"');
  });
  it("uses the one shared page header and does not advertise operator tabs to visitors", () => {
    const html = renderToStaticMarkup(<Workspace title="الأعمال" intro="تعريف"><p>Content</p></Workspace>);
    expect(html).toContain('hx-head');
    expect(html).toContain('href="/ar/business"');
    expect(html).toContain('aria-current="page"');
    expect(html).not.toContain('/operations/verification');
    expect(html).not.toContain('/business/contacts');
    expect(html.match(/<h1/g)).toHaveLength(1);
  });
});
