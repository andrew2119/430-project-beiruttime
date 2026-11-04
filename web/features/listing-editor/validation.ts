import type { Copy } from "./copy";
const names: Record<string, keyof Copy> = {
  brand: "brand",
  model: "model",
  reference: "reference",
  year: "year",
  condition: "condition",
  location: "location",
  price_minor: "price",
  component_wear: "wear",
  ownership_confirmed: "ownership",
  modified: "modifiedQuestion",
  modifications: "disclosure",
  photos: "photos",
  component: "component",
  modifier: "modifier",
  warranty_issuer: "warranty",
  provenance: "provenance",
  case: "case",
  dial: "dial",
  crystal: "crystal",
  bracelet: "bracelet",
  movement: "movement",
};
export function correctionFields(fields: unknown): (keyof Copy)[] {
  if (!Array.isArray(fields)) return [];
  const labels = fields
    .slice(0, 50)
    .map((field) => {
      const path =
        typeof field === "string"
          ? field
          : field && typeof field === "object" && typeof field.path === "string"
            ? field.path
            : "";
      const name = path.split(".").at(-1) ?? "";
      return Object.hasOwn(names, name) ? names[name] : null;
    })
    .filter((label): label is keyof Copy => label !== null);
  return [...new Set(labels)];
}
