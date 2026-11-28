import guidance from '@contracts/contracts-comms/help-policies/guidance.v1.json';
import type { HelpArticle } from '@contracts/contracts-comms/help-policies/v1';
export const policyGuidance = guidance;
/** Search both versions so changing the reading language preserves results. */
export function helpMatches(query:string, items:readonly HelpArticle[] = guidance.articles) {
  const needle = query.slice(0,200).trim().toLocaleLowerCase();
  return items.filter(item=>[item.en.title,item.en.body,item.ar.title,item.ar.body].some(value=>value.toLocaleLowerCase().includes(needle)));
}
