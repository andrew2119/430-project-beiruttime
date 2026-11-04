"""Verify copied foundation bytes against a merged reference; never remove files."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--reference", default="origin/main")
    parser.add_argument("--extra", action="append", default=[])
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    if not snapshot.is_dir():
        raise SystemExit("Provide the read-only foundation snapshot directory")
    paths = {
        path.relative_to(snapshot).as_posix()
        for path in snapshot.rglob("*")
        if path.is_file()
        and not {".git", "node_modules", ".next", ".venv"}.intersection(path.relative_to(snapshot).parts)
    }
    paths.update(args.extra)
    if (ROOT / "infra/foundation/context-smoke.py").exists():
        paths.add("infra/foundation/context-smoke.py")
    mismatches = []
    for relative in sorted(paths):
        current = (ROOT / relative).resolve()
        if not current.is_relative_to(ROOT):
            raise SystemExit("A comparison path escapes the checkout")
        reference = subprocess.run(["git", "show", args.reference + ":" + relative], cwd=ROOT, capture_output=True)
        if reference.returncode:
            mismatches.append({"path": relative, "reason": "not_in_reference"})
            continue
        if not current.is_file():
            mismatches.append({"path": relative, "reason": "missing_local_copy"})
            continue
        actual = current.read_bytes()
        if actual != reference.stdout:
            mismatches.append(
                {
                    "path": relative,
                    "reason": "bytes_differ",
                    "local_sha256": hashlib.sha256(actual).hexdigest(),
                    "reference_sha256": hashlib.sha256(reference.stdout).hexdigest(),
                }
            )
    print(json.dumps({"files": len(paths), "identical": not mismatches, "mismatches": mismatches}, indent=2))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
