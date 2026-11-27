import type { WatchFacts } from "@contracts/contracts-catalog/listings/v1";
import type { Copy } from "./copy";

export function CurrentFacts({facts, t}: {facts: WatchFacts; t: Copy}) {
  const rows: [string, string | number][] = [
    ...(["brand", "model", "reference", "year", "condition", "location"] as const).map(key => [t[key], facts[key] ?? t.unavailable] as [string, string | number]),
    [t.price, facts.price_minor === null ? t.unavailable : (facts.price_minor / 100).toFixed(2)],
    [t.saleMode, t[facts.sale_mode]],
    [t.included, facts.included.map(item => t[item]).join("، ") || t.noDocuments],
    [t.noDocuments, facts.no_documents ? t.confirmedYes : t.confirmedNo],
    [t.ownership, facts.ownership_confirmed ? t.confirmedYes : t.confirmedNo],
    [t.modifiedQuestion, facts.modified === null ? t.unavailable : facts.modified ? t.yes : t.no],
    ...(["case", "dial", "crystal", "bracelet", "movement"] as const).map(key => [t[key], facts.component_wear[key] || t.unavailable] as [string, string]),
    ...facts.modifications.flatMap(item => ([
      [t.component, item.component], [t.provenance, t[item.provenance]],
      [t.modifier, item.modifier], [t.warranty, item.warranty_issuer], [t.notes, item.notes],
    ] as [string, string][])),
  ];
  return <dl className="le-review le-current-facts">{rows.map(([label, value], index) => <div key={index}><dt>{label}</dt><dd dir="auto">{value || t.unavailable}</dd></div>)}</dl>;
}
