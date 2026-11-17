import type { Report, ReportRequest } from '@contracts/contracts-orders/financial-reports';
import { ExportFence } from './export-fence';
import { validateReport } from './reads';

/** Only a freshly authorized answer may reach the print surface. */
export async function printCurrent(fence:ExportFence,read:(signal:AbortSignal)=>Promise<Report>,request:ReportRequest,print:(answer:Report)=>void) {
  const controller=fence.begin();
  if (!controller)return false;
  try {
    const answer=validateReport(await read(controller.signal),request);
    if (!fence.accepts(controller) || answer.state!=='ready')return false;
    print(answer);
    return true;
  } catch {return false;}
  finally {fence.finish(controller);}
}
