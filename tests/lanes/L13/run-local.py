"""Restricted disposable-database checks against shared local PostgreSQL, no domain migrations."""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
service = sys.argv[1] if len(sys.argv) > 1 else "orders"
if service not in {"orders", "auction", "catalog"}:
    raise SystemExit("Select orders, auction or catalog")
config = json.loads(
    subprocess.check_output(
        [str(ROOT / "infra/foundation/compose.sh"), "config", "--format", "json"]
    )
)
postgres = config["services"]["postgres"]
password = postgres["environment"]["POSTGRES_PASSWORD"]
port = next(p["published"] for p in postgres["ports"] if p["target"] == 5432)
source_paths = [
    ROOT / "packages" / name / "src"
    for name in ("runtime", "contracts-core", "events", "bulkheads")
]
source_paths += [
    ROOT / ".venv/l13-contracts",
    ROOT / f"services/{service}/runtime",
    ROOT / f"services/{service}",
]
env = {
    **os.environ,
    "BT_SERVICE_NAME": service,
    "BT_MODULES_PATH": str(ROOT / f"services/{service}/modules"),
    "TEST_DATABASE_ADMIN_URL": f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres",
    "PYTHONPATH": os.pathsep.join(map(str, source_paths)),
}
paths = [str(ROOT / f"tests/lanes/L13/{service}")]
if service == "orders":
    paths += [
        str(ROOT / "services/orders/runtime/tests"),
        str(ROOT / "services/orders/modules"),
        str(ROOT / "tests/lanes/L08/orders"),
    ]
raise SystemExit(
    subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "bt_runtime.testing",
            "-c",
            str(ROOT / f"services/{service}/runtime/pyproject.toml"),
            *paths,
            "-q",
            *sys.argv[2:],
        ],
        cwd=ROOT,
        env=env,
    )
)
