import type { QualityCommand, QualityLine } from '@contracts/contracts-service/quality/v1';
export type Entry = { actual: string; result: '' | 'pass' | 'fail' };
export type LineDraft = { line_id: string; tests: Record<string, Entry>; condition: Entry; fit: Entry; returned_parts: Entry };
export const fields = ['condition', 'fit', 'returned_parts'] as const;
export function blank(line_id: string, testKeys: string[] = ['tests']): LineDraft {
  return { line_id, tests: Object.fromEntries(testKeys.map(key=>[key,{actual:'',result:'' as const}])), condition:{actual:'',result:''}, fit:{actual:'',result:''}, returned_parts:{actual:'',result:''} };
}
export function complete(lines: LineDraft[]) {
  return lines.length > 0 && lines.every(line=>[...Object.values(line.tests),...fields.map(key=>line[key])].every(entry=>entry.actual.length > 0 && /^\S/.test(entry.actual) && entry.actual.length <= 2000 && entry.result !== ''));
}
export function commandLines(lines: LineDraft[]): QualityLine[] {
  if (!complete(lines)) throw new Error('incomplete');
  return lines.map(line=>{
    const check = (key: typeof fields[number])=>({key,actual:line[key].actual,satisfactory:line[key].result==='pass'});
    return {line_id:line.line_id,tests:Object.entries(line.tests).map(([key,entry])=>({key,actual:entry.actual,satisfactory:entry.result==='pass'})),condition:check('condition'),fit:check('fit'),returned_parts:check('returned_parts')};
  });
}
export type Context = Omit<QualityCommand, 'schema_version' | 'operation_id' | 'lines'> & { total?: number; line_ids: string[]; test_keys: Record<string, string[]> };
export function validContext(context: Context) {
  return (context.total === undefined || (Number.isSafeInteger(context.total) && context.total >= context.line_ids.length && context.total <= 1000)) && context.line_ids.length > 0 && context.line_ids.length <= 1000 && new Set(context.line_ids).size === context.line_ids.length && context.line_ids.every(id=>{const keys=context.test_keys[id]; return keys?.length > 0 && keys.length <= 30 && new Set(keys).size===keys.length;});
}
export function makeCommand(context: Context, lines: LineDraft[], operation_id: string): QualityCommand {
  const {line_ids, test_keys, total, ...binding} = context;
  if ((total !== undefined && total !== lines.length) || !validContext(context) || lines.some(line=>Object.keys(line.tests).length!==test_keys[line.line_id]?.length || Object.keys(line.tests).some(key=>!test_keys[line.line_id]?.includes(key))) || line_ids.length !== lines.length || lines.some(line=>!line_ids.includes(line.line_id))) throw new Error('invalid_scope');
  return {...binding,schema_version:'quality.v1',operation_id,lines:commandLines(lines)};
}
