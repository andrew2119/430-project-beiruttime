import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ClipboardList } from "lucide-react";
import { describe, expect, it } from "vitest";
import { HeaderTabs, Select } from '@beirut-time/ui';
import { ListingSkeleton } from './row-skeleton';

describe("Shared seller controls", () => {
  it.each(["Watch details", "تفاصيل الساعة"])('keeps the translated "%s" tab and locked Pane anatomy', label => {
    const html = renderToStaticMarkup(createElement(HeaderTabs, {
      items: [{ id: "facts", label, icon: ClipboardList }, { id: "review", label: "Review", icon: ClipboardList }],
      value: "facts", onChange: () => {}, label,
    }));
    expect(html).toContain('data-look="pane"');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('role="tab" aria-selected="true"');
    expect(html).toContain('role="tab" aria-selected="false"');
    expect(html).toContain('hx-tabs-rulerbox');
    expect(html).toContain(label);
  });
  it("reserves the source cover geometry while announcing loading once", () => {
    const html = renderToStaticMarkup(createElement(ListingSkeleton, {label:"Loading watches"}));
    expect(html).toContain('role="status" aria-label="Loading watches"');
    expect(html.match(/pg-skeleton-media-cover/g)).toHaveLength(5);
    expect(html.match(/pg-skeleton-copy/g)).toHaveLength(5);
  });
  it("keeps the lazy Select trigger named, disabled and selected without mounting a menu", () => {
    const html = renderToStaticMarkup(createElement(Select, {
      value:"auction", options:[{value:"auction",label:"Ordinary auction"}],
      "aria-label":"Sale method", onValueChange:() => {}, disabled:true,
    }));
    expect(html).toContain('aria-label="Sale method"');
    expect(html).toContain('aria-haspopup="menu" aria-expanded="false"');
    expect(html).toContain('disabled=""');
    expect(html).toContain('Ordinary auction');
    expect(html).not.toContain('role="menu"');
  });
});
