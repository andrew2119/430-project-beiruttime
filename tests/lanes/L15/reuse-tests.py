"""Run Catalog regression lanes against this checkout's existing test image."""

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

root = Path(__file__).resolve().parents[3]
os.chdir(root)
prefix = (
    "beirut-time/catalog:test-"
    + hashlib.sha256(str(root).encode()).hexdigest()[:8]
    + "-"
)
if len(sys.argv) < 2 or not sys.argv[1].startswith(prefix):
    raise SystemExit("Pass the existing Catalog test image built in this checkout")
config = json.loads(
    subprocess.check_output(
        ["./infra/foundation/compose.sh", "config", "--format", "json"]
    )
)
env = {
    **os.environ,
    "BT_SERVICE_NAME": "catalog",
    "TEST_DATABASE_ADMIN_URL": f"postgresql://postgres:{config['services']['postgres']['environment']['POSTGRES_PASSWORD']}@postgres:5432/postgres",
    "TEST_RUNTIME_URL": config["services"]["catalog"]["environment"]["BT_DATABASE_URL"],
}
allowed_lanes = ("L03", "L04", "L08", "L10", "L11", "L15")
lanes = sys.argv[2:] or allowed_lanes
if not set(lanes) <= set(allowed_lanes):
    raise SystemExit("Select a Catalog regression lane")
mounts = []
for source, target in [
    ("services/catalog/modules", "/app/modules"),
    ("services/catalog/runtime/service_app", "/app/service_app"),
    ("tests/lanes", "/lane-tests"),
    (
        "packages/contracts-catalog/configuration",
        "/opt/domain-contracts/bt_contracts/catalog/configuration",
    ),
    (
        "packages/contracts-catalog/request-drafts",
        "/opt/domain-contracts/bt_contracts/catalog/request_drafts",
    ),
    (
        "packages/contracts-catalog/brand-decisions",
        "/opt/domain-contracts/bt_contracts/catalog/brand_decisions",
    ),
]:
    mounts.extend(["-v", str(root / source) + ":" + target + ":ro"])
for lane in lanes:
    print(f"Catalog regression {lane}", flush=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--name", f'bt-l15-test-{prefix.rsplit("-",2)[-2]}-{lane.lower()}-{uuid4().hex[:8]}',
            "--memory",
            "384m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "128",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--network",
            config["name"] + "_default",
            *mounts,
            "-e",
            "TEST_DATABASE_ADMIN_URL",
            "-e",
            "TEST_RUNTIME_URL",
            "-e",
            "BT_SERVICE_NAME",
            "-e",
            f"BT_TEST_LANE={lane}",
            sys.argv[1],
        ],
        env=env,
        check=True,
    )
