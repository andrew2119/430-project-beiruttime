"""Common proofs plus an optional lane suite, without a Dockerfile/index edit."""
import os
from pathlib import Path
import re
import pytest

lane = os.environ.get('BT_TEST_LANE', 'L00')
if not re.fullmatch(r'L(0[0-9]|1[01])', lane):
    raise SystemExit('BT_TEST_LANE must be L00 through L11')
paths = ['tests', 'modules', '/foundation-tests', '/lane-tests/L00']
if lane != 'L00':
    root = Path('/lane-tests') / lane
    service_root = root / os.environ.get('BT_SERVICE_NAME', '')
    paths.append(str(service_root if service_root.is_dir() and service_root != root else root))
raise SystemExit(pytest.main(['-c', '/app/pyproject.toml', *paths, '-q', '-o', 'cache_dir=/tmp/pytest-cache']))
