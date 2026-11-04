import en from "./en.json";
import ar from "./ar.json";
export type Copy = typeof en;
export function copy(locale: string): Copy {
  return locale === "ar" ? ar : en;
}
