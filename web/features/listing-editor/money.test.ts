import { describe, it, expect } from "vitest";
import { parseMinor } from "./money";
import en from "./en.json";
import ar from "./ar.json";

describe("exact listing input", () => {
  it("normalizes Arabic and Persian digits without float rounding", () => {
    expect(parseMinor("١٨٠٫٢٩")).toBe(18029);
    expect(parseMinor("۱۸۰.۲۹")).toBe(18029);
    expect(parseMinor("0.29")).toBe(29);
    expect(parseMinor("180")).toBe(18000);
    expect(parseMinor("1.2")).toBe(120);
  });
  it("rejects ambiguous, negative, nonfinite and over-precision values", () => {
    for (const value of [
      "",
      "0",
      "-1",
      "NaN",
      "Infinity",
      "1e3",
      "1.001",
      "1,000.00",
      "99999999999",
    ])
      expect(parseMinor(value)).toBeNull();
  });
  it("keeps every owned EN and AR key aligned and nonempty", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ar).sort());
    expect(Object.values(ar).every((value) => value.length > 0)).toBe(true);
  });
});
