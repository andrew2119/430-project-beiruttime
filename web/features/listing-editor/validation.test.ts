import { it, expect } from "vitest";
import { correctionFields } from "./validation";
it("turns both domain and validation paths into closed translated field names", () => {
  expect(
    correctionFields([
      "brand",
      { path: "body.facts.year", input: "private rejected value" },
      "brand",
      "__proto__",
      "untrusted text",
    ]),
  ).toEqual(["brand", "year"]);
  expect(
    correctionFields([{ path: "body.facts.modifications.0.warranty_issuer" }]),
  ).toEqual(["warranty"]);
  expect(correctionFields(null)).toEqual([]);
});
