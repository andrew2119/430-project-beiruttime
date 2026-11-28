"""Run focused synthetic checks and print a bounded result manifest."""
import json
import subprocess
import sys
from pathlib import Path

from restore import CONTRACT


def main():
    root = Path(__file__).parent
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         str(root / "test_restore.py"), str(root / "test_migrations.py")],
        timeout=120, check=False, capture_output=True, text=True,
    )
    # Test details remain separate from the machine-readable result.
    print(result.stdout, file=sys.stderr, end="")
    print(result.stderr, file=sys.stderr, end="")
    print(json.dumps({
        "schema_version": CONTRACT["schema_version"], "synthetic": True,
        "result": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode, "connected": "deferred",
        "skipped": ["connected execution", "heavy execution", "physical phone"],
        "remaining_proof": CONTRACT["remaining_proof"],
    }, sort_keys=True))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
