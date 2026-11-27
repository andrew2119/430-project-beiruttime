import { usesFoundationShell } from '@/shell/foundation/path';
import IntakeBoundary from './index';

export default function IntakeRoute({screen}: {screen: 'intake'}) {
  return <IntakeBoundary screen={screen} mountedRead={!usesFoundationShell('/business-intake')}/>;
}
