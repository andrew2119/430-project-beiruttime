"""Reuse existing images for real Identity + isolated-draft browser proofs.

No token fixtures, privileged buyer grants, shared-runtime restart, shared-image
cleanup or authoritative Catalog replacement. Printed metadata contains no credentials.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import httpx

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
STATE = ROOT / "node_modules/l08-live-proofs.json"
ORIGINS = ("http://localhost:3108", "http://127.0.0.1:3108")


def output(*command):
    return subprocess.check_output(command, text=True)


def run(*command, **options):
    return subprocess.run(command, check=True, **options)


def bind(source, target):
    return ["--mount", f"type=bind,source={source},target={target},readonly"]


def inspect_container(name):
    return json.loads(output("docker", "inspect", name))[0]


def port(name):
    bindings = inspect_container(name)["NetworkSettings"]["Ports"]["8000/tcp"]
    if len(bindings) != 1 or bindings[0]["HostIp"] != "127.0.0.1":
        raise RuntimeError("Proof listener must be loopback-only")
    return int(bindings[0]["HostPort"])


def ready(url):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            if httpx.get(url + "/health/ready", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError("Proof runtime did not become ready")


def start():
    if STATE.exists():
        raise SystemExit("A proof state already exists; stop it before starting another")
    original = inspect_container("beirut-time-identity-1")
    config = json.loads(output("./infra/foundation/compose.sh", "config", "--format", "json"))
    network = config["name"] + "_default"
    source = ROOT / "node_modules/l08-live-source"
    source.mkdir(parents=True, exist_ok=True)
    modules = source / "catalog-modules"
    shutil.copytree(
        ROOT / "services/catalog/modules/request-drafts",
        modules / "request-drafts",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    contracts = source / "contracts"
    run("python3", "infra/foundation/package-contracts.py", str(contracts))
    tag = json.loads((ROOT / "node_modules/l08-test-base.json").read_text())["tag"]
    run("docker", "image", "inspect", tag, stdout=subprocess.DEVNULL)
    identity = f"bt-l08-identity-proof-{os.getpid()}"
    catalog = f"bt-l08-draft-proof-{os.getpid()}"
    names = []
    try:
        # Preserve the real issuer/database/signing configuration in memory; never print or persist it.
        values = dict(entry.split("=", 1) for entry in original["Config"]["Env"])
        existing = values.get("BT_ALLOWED_WEB_ORIGINS") or values.get("BT_WEB_ORIGIN", "http://localhost:3000")
        values["BT_ALLOWED_WEB_ORIGINS"] = ",".join(dict.fromkeys([*existing.split(","), *ORIGINS]))
        env = {**os.environ, **values}
        flags = [flag for key in values for flag in ("-e", key)]
        budget = [
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
            network,
            "-p",
            "127.0.0.1::8000",
        ]
        run(
            "docker",
            "run",
            "-d",
            "--init",
            "--name",
            identity,
            *budget,
            "--volumes-from",
            "beirut-time-identity-1:ro",
            *flags,
            original["Image"],
            stdout=subprocess.DEVNULL,
            env=env,
        )
        names.append(identity)
        identity_port = port(identity)
        ready(f"http://127.0.0.1:{identity_port}")
        password = config["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
        env = {
            **os.environ,
            "TEST_DATABASE_ADMIN_URL": f"postgresql://postgres:{password}@postgres:5432/postgres",
            "BT_SERVICE_NAME": "catalog",
            "BT_MODULES_PATH": "/app/modules",
            "BT_IDENTITY_URL": f"http://{identity}:8000",
        }
        mounts = (
            bind(modules, "/app/modules")
            + bind(contracts, "/opt/domain-contracts")
            + bind(ROOT / "tests/lanes/L08/live-draft-proof.py", "/app/live_draft_proof.py")
        )
        for package, module in {
            "runtime": "bt_runtime",
            "events": "bt_events",
            "bulkheads": "bt_bulkheads",
            "contracts-core": "bt_contracts_core",
        }.items():
            mounts += bind(
                ROOT / "packages" / package / "src" / module, "/opt/venv/lib/python3.11/site-packages/" + module
            )
        flags = [
            flag
            for key in ("TEST_DATABASE_ADMIN_URL", "BT_SERVICE_NAME", "BT_MODULES_PATH", "BT_IDENTITY_URL")
            for flag in ("-e", key)
        ]
        run(
            "docker",
            "run",
            "-d",
            "--init",
            "--name",
            catalog,
            *budget,
            *mounts,
            *flags,
            tag,
            "python",
            "/app/live_draft_proof.py",
            stdout=subprocess.DEVNULL,
            env=env,
        )
        names.append(catalog)
        catalog_port = port(catalog)
        ready(f"http://127.0.0.1:{catalog_port}")
        state = {
            "containers": names,
            "identity_url": f"http://127.0.0.1:{identity_port}",
            "catalog_url": f"http://127.0.0.1:{catalog_port}",
            "web_origins": list(ORIGINS),
            "isolated_draft_database": True,
            "full_slice_accepted": False,
        }
        STATE.write_text(json.dumps(state, indent=2) + "\n")
        print(json.dumps(state))
    except BaseException:
        for name in reversed(names):
            subprocess.run(["docker", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise


def stop():
    if not STATE.exists():
        return
    state = json.loads(STATE.read_text())
    for name in reversed(state["containers"]):
        if not name.startswith(("bt-l08-identity-proof-", "bt-l08-draft-proof-")):
            raise RuntimeError("Foreign proof name refused")
        run("docker", "stop", name, stdout=subprocess.DEVNULL)
    STATE.unlink()
    print("Owned proof listeners stopped; shared runtime and images retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    start() if args.action == "start" else stop()
