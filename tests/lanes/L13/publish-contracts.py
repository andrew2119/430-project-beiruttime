"""Refresh only this lane's authorized, versioned provider source previews."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import shutil
from portable_paths import contracts_dir

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED = contracts_dir(ROOT)
OMIT = {"__pycache__", ".pytest_cache", ".ruff_cache", ".DS_Store"}


def files(paths):
    result = set()
    for name in paths:
        path = ROOT / name
        for item in [path] if path.is_file() else path.rglob("*"):
            if (
                item.is_file()
                and not OMIT.intersection(item.parts)
                and item.suffix not in {".pyc", ".pyo"}
            ):
                result.add(item.relative_to(ROOT))
    return sorted(result)


def publish(name, paths, archive="implementation.tar.gz"):
    destination = PUBLISHED / name
    destination.mkdir(parents=True, exist_ok=True)
    source = files(paths)
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True
    ).strip()
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    manifest = {
        "baseline_commit": head,
        "source_commit": None if dirty else head,
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True
        ).strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "provenance": "uncommitted working source preview"
        if dirty
        else "committed source",
        "sha256": {
            str(p): hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source
        },
    }
    with tarfile.open(destination / archive, "w:gz") as output:
        for path in source:
            output.add(ROOT / path, arcname=str(path))
    (destination / "implementation-sha256.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return destination


orders = publish(
    "orders-commitment/v2",
    [
        "services/orders/runtime",
        "services/orders/modules/allocation",
        "services/orders/modules/payments",
        "services/orders/modules/journal",
        "packages/contracts-orders/allocation",
        "packages/contracts-orders/payments",
        "packages/contracts-orders/journal",
        "packages/contracts-auction/closing",
        "packages/contracts-catalog/withdrawal",
        "contracts/registrations/L13.json",
    ],
)
closing = publish(
    "auction-close/v1",
    ["services/auction/modules/closing", "packages/contracts-auction/closing"],
)
withdrawal = publish(
    "listing-withdrawal/v1",
    ["services/catalog/modules/withdrawal", "packages/contracts-catalog/withdrawal"],
)
payments = publish(
    "payment-journal/v1",
    [
        "services/orders/modules/payments",
        "services/orders/modules/journal",
        "packages/contracts-orders/payments",
        "packages/contracts-orders/journal",
    ],
)
for destination, target, source in [
    (
        orders,
        "orders_kernel.py",
        "services/orders/runtime/service_app/orders_kernel.py",
    ),
    (orders, "v2.py", "packages/contracts-orders/allocation/v2.py"),
    (closing, "closing-schema.py", "packages/contracts-auction/closing/__init__.py"),
    (withdrawal, "schema.py", "packages/contracts-catalog/withdrawal/__init__.py"),
    (payments, "payments-schema.py", "packages/contracts-orders/payments/__init__.py"),
    (payments, "index.ts", "packages/contracts-orders/payments/index.ts"),
    (payments, "paid-facts.py", "packages/contracts-orders/journal/facts.py"),
]:
    (destination / target).write_bytes((ROOT / source).read_bytes())
resolution = PUBLISHED / "orders-commitment/v2.1"
resolution.mkdir(parents=True, exist_ok=True)
for name in (
    "implementation.tar.gz",
    "implementation-sha256.json",
    "orders_kernel.py",
    "v2.py",
):
    shutil.copyfile(orders / name, resolution / name)
shutil.copyfile(
    ROOT
    / "services/orders/modules/allocation/commitment/migrations/L13_0002_edit_resolution.sql",
    resolution / "L13_0002_edit_resolution.sql",
)
print("Refreshed owned source previews and exact-byte provenance manifests")
