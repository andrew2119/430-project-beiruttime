"""Read-only preflight: no foreign source file may enter the feature diff."""

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OWNED = (
    "services/orders/runtime/",
    "services/orders/modules/allocation/",
    "services/catalog/modules/request-drafts/",
    "web/app/(buy-now)/checkout/",
    "web/app/(brand-requests)/custom-requests/",
    "web/features/buy-now/",
    "web/features/request-drafts/",
    "packages/contracts-orders/allocation/",
    "packages/contracts-catalog/request-drafts/",
    "tests/integration/sprint-1/",
    "tests/lanes/L08/",
)
EXACT = {"web/registrations/L08.ts", "infra/compose/L08.yaml", "contracts/registrations/L08.json"}


def owned(path):
    if path.startswith("/") or ".." in Path(path).parts:
        return False
    return path in EXACT or any(path.startswith(prefix) for prefix in OWNED)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--reference", default="origin/main")
    args = parser.parse_args()
    if (
        not args.staged
        and subprocess.run(["git", "merge-base", "--is-ancestor", args.reference, "HEAD"], cwd=ROOT).returncode
    ):
        raise SystemExit("Merge the current reference before validating the publication diff")
    incoming = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    if args.staged:
        # A normal merge stages upstream-owned inputs too; check only our contribution to it.
        command = ["git", "diff", "--name-only", "--cached"] + (
            [incoming.stdout.strip()] if incoming.returncode == 0 else []
        )
    else:
        command = ["git", "diff", "--name-only", args.reference + "...HEAD"]
    paths = subprocess.check_output(command, cwd=ROOT, text=True).splitlines()
    foreign = [path for path in paths if not owned(path)]
    print(json.dumps({"files": len(paths), "owned_only": bool(paths) and not foreign, "foreign": foreign}))
    return 0 if paths and not foreign else 1


if __name__ == "__main__":
    raise SystemExit(main())
