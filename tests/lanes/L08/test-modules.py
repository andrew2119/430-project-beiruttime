"""Current-source PostgreSQL proofs using one reusable, checkout-local dependency image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

root = Path(__file__).resolve().parents[3]
os.chdir(root)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def mount(source, target):
    return ["--mount", f"type=bind,source={source},target={target},readonly"]


def available(tag):
    return (
        subprocess.run(
            ["docker", "image", "inspect", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        == 0
    )


parser = argparse.ArgumentParser()
parser.add_argument(
    "--reuse-image", help="Reuse a previously built L08 dependency image; current source is always mounted"
)
parser.add_argument(
    "--build-dependencies", action="store_true", help="Rebuild only when the dependency environment needs refreshing"
)
args = parser.parse_args()
checkout = hashlib.sha256(str(root).encode()).hexdigest()[:8]
inputs = [
    root / "services/orders/runtime" / name for name in ["Dockerfile", "requirements.txt", "requirements-dev.txt"]
]
inputs += [root / "packages" / name / "pyproject.toml" for name in ["runtime", "events", "bulkheads", "contracts-core"]]
digest = hashlib.sha256(b"".join(path.read_bytes() for path in inputs)).hexdigest()
cache = root / "node_modules/l08-test-base.json"
previous = json.loads(cache.read_text()) if cache.exists() else {}
if args.reuse_image and previous and previous.get("dependency_digest") != digest:
    raise SystemExit(
        "Dependency manifests changed; refresh the dependency image instead of overriding its cached provenance"
    )
tag = args.reuse_image or (previous.get("tag") if previous.get("dependency_digest") == digest else None)
if tag and not tag.startswith(f"beirut-time/l08:test-{checkout}-"):
    raise SystemExit("Select only this checkout's L08 test image")
if args.build_dependencies or not tag or not available(tag):
    if args.reuse_image and not available(args.reuse_image):
        raise SystemExit("The requested local test image is unavailable; no pull was attempted")
    tag = f"beirut-time/l08:test-{checkout}-deps-{digest[:12]}"
    run(
        "docker",
        "build",
        "--target",
        "test",
        "-f",
        "services/orders/runtime/Dockerfile",
        "--build-arg",
        "SERVICE_PATH=services/orders",
        "-t",
        tag,
        ".",
    )
cache.parent.mkdir(parents=True, exist_ok=True)
cache.write_text(json.dumps({"tag": tag, "dependency_digest": digest}))
print("Reuse dependency image with current owned source:", tag, flush=True)
config = json.loads(subprocess.check_output(["./infra/foundation/compose.sh", "config", "--format", "json"]))
shared = {
    "runtime": "bt_runtime",
    "events": "bt_events",
    "bulkheads": "bt_bulkheads",
    "contracts-core": "bt_contracts_core",
}
with TemporaryDirectory(prefix="l08-proof-", dir=root / "node_modules") as temporary:
    temporary = Path(temporary)
    contracts = temporary / "contracts"
    run("python3", "infra/foundation/package-contracts.py", str(contracts))
    common = mount(contracts, "/opt/domain-contracts")
    for package, module in shared.items():
        common += mount(
            root / "packages" / package / "src" / module, "/opt/venv/lib/python3.11/site-packages/" + module
        )
    for source, target in [
        ("services/orders/runtime/service_app", "/app/service_app"),
        ("services/orders/runtime/tests", "/app/tests"),
        ("services/orders/runtime/pyproject.toml", "/app/pyproject.toml"),
        ("services/orders/runtime/conftest.py", "/app/conftest.py"),
        ("services/orders/runtime/run_tests.py", "/app/run_tests.py"),
        ("tests/foundation", "/foundation-tests"),
        ("tests/lanes/L00", "/lane-tests/L00"),
        ("tests/lanes/L08", "/lane-tests/L08"),
        ("contracts", "/contracts"),
    ]:
        common += mount(root / source, target)
    for service, module in [("orders", "allocation"), ("catalog", "request-drafts")]:
        modules = temporary / service
        # Unit proofs load only the owned module, never another domain's runtime or writers.
        shutil.copytree(
            root / "services" / service / "modules" / module,
            modules / module,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        password = config["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
        env = {
            **os.environ,
            "TEST_DATABASE_ADMIN_URL": f"postgresql://postgres:{password}@postgres:5432/postgres",
            "TEST_RUNTIME_URL": config["services"][service]["environment"]["BT_DATABASE_URL"],
            "BT_SERVICE_NAME": service,
            "BT_TEST_LANE": "L08",
        }
        # Finished proof containers stay stopped for later review; shared storage/cache is untouched.
        run(
            "docker",
            "run",
            "--name",
            f"bt-l08-proof-{service}-{os.getpid()}",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "128",
            "--network",
            config["name"] + "_default",
            *common,
            *mount(modules, "/app/modules"),
            "-e",
            "TEST_DATABASE_ADMIN_URL",
            "-e",
            "TEST_RUNTIME_URL",
            "-e",
            "BT_SERVICE_NAME",
            "-e",
            "BT_TEST_LANE",
            tag,
            env=env,
        )
