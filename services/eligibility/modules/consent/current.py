"""Load the published private current-context contract at the evidence boundary."""
import importlib.util
from pathlib import Path

paths = (Path('/opt/domain-contracts/contracts-eligibility/decisions/v1.py'),
         Path(__file__).resolve().parents[4] / 'packages/contracts-eligibility/decisions/v1.py')
path = next((candidate for candidate in paths if candidate.is_file()), None)
if path is None:
    raise RuntimeError('Eligibility current contract missing')
spec = importlib.util.spec_from_file_location('eligibility_consent_current_v1', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Current = module.Current
