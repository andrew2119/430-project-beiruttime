import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import type { WatchFacts } from "@contracts/contracts-catalog/listings/v1";
import { CurrentFacts } from "./current-facts";
import { copy } from "./copy";

it.each(["en", "ar"] as const)("labels the current facts for review in %s", locale => {
  const facts: WatchFacts = {brand: "ساعة Reference ⌚", model: "Watch", reference: "Reference", year: 2020,
    condition: "Wear", component_wear: {case: "Wear"}, location: "Beirut", included: ["papers"],
    no_documents: false, modified: true, modifications: [{component: "Dial", provenance: "aftermarket", modifier: "Declared", warranty_issuer: "None", notes: "Wear"}],
    ownership_confirmed: true, sale_mode: "fixed_price", currency: "USD", price_minor: 500001};
  const t = copy(locale);
  const html = renderToStaticMarkup(createElement(CurrentFacts, {facts, t}));
  expect(html).toContain(t.brand);
  expect(html).toContain(t.aftermarket);
  expect(html).toContain(t.fixed_price);
  expect(html).toContain("5000.01");
  expect(html).not.toContain("price_minor");
  expect(html).not.toContain("warranty_issuer");
});
