"""Reuse pinned domain test images; thin source overlays, isolated tests, own Compose proof.
Run through bt-heavy.sh --build. No dependency rebuilds, volumes, cache cleanup or shared restarts.
"""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import shutil
import httpx

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
config = json.loads(
    subprocess.check_output(
        ["./infra/foundation/compose.sh", "config", "--format", "json"]
    )
)
password = config["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
network = config["name"] + "_default"
slug = hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
env = {
    **os.environ,
    "TEST_DATABASE_ADMIN_URL": f"postgresql://postgres:{password}@postgres:5432/postgres",
}
shutil.rmtree(ROOT / "tests/lanes/L13/.contracts", ignore_errors=True)
subprocess.run(
    [
        sys.executable,
        "infra/foundation/package-contracts.py",
        "tests/lanes/L13/.contracts",
    ],
    check=True,
)
services = {}
for name, port in [("orders", 58136), ("catalog", 58137), ("auction", 58138)]:
    base = f"beirut-time/{name}:l13-proof-{slug}"
    subprocess.run(
        ["docker", "image", "inspect", base], check=True, stdout=subprocess.DEVNULL
    )
    tag = f"beirut-time/{name}:l13-current-{slug}"
    # Original Dockerfile/dependencies have already built and passed. Refresh only COPY layers.
    inputs = [
        ROOT / f"services/{name}/runtime",
        ROOT / f"services/{name}/modules",
        ROOT / "tests/lanes/L13/.contracts",
        ROOT / f"tests/lanes/L13/{name}",
        ROOT / "tests/lanes/L13/proof-service.py",
        ROOT / "tests/lanes/L13/Dockerfile.proof",
        *[
            ROOT / "packages" / package / "src"
            for package in ("runtime", "events", "bulkheads", "contracts-core")
        ],
    ]
    digest = hashlib.sha256()
    for root in inputs:
        files = (
            [root]
            if root.is_file()
            else sorted(
                p
                for p in root.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            )
        )
        for file in files:
            digest.update(str(file.relative_to(ROOT)).encode())
            digest.update(file.read_bytes())
    fingerprint = digest.hexdigest()
    current = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            tag,
            "--format",
            '{{index .Config.Labels "io.beirut.l13.digest"}}',
        ],
        capture_output=True,
        text=True,
    )
    if current.returncode != 0 or current.stdout.strip() != fingerprint:
        subprocess.run(
            [
                "docker",
                "build",
                "-f",
                "tests/lanes/L13/Dockerfile.proof",
                "--build-arg",
                "BASE_IMAGE=" + base,
                "--build-arg",
                "SERVICE_PATH=services/" + name,
                "--label",
                "io.beirut.l13.digest=" + fingerprint,
                "-t",
                tag,
                ".",
            ],
            check=True,
        )
    env["TEST_RUNTIME_URL"] = config["services"][name]["environment"]["BT_DATABASE_URL"]
    paths = ["/app/tests", "/app/modules", "/lane-tests/L13/" + name]
    if name == "orders":
        paths.append("/lane-tests/L08/orders")
    subprocess.run(
        [
            "docker",
            "run",
            "--name",
            f"bt-l13-{name}-tests-{os.getpid()}",
            "--memory",
            "256m",
            "--cpus",
            ".5",
            "--pids-limit",
            "128",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--network",
            network,
            "-e",
            "TEST_DATABASE_ADMIN_URL",
            "-e",
            "TEST_RUNTIME_URL",
            "-e",
            "BT_SERVICE_NAME=" + name,
            "-e",
            "BT_MODULES_PATH=/app/modules",
            tag,
            "python",
            "-m",
            "pytest",
            "-p",
            "bt_runtime.testing",
            "-c",
            "/app/pyproject.toml",
            *paths,
            "-q",
            "-o",
            "cache_dir=/tmp/pytest-cache",
        ],
        check=True,
        env=env,
    )
    subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
    services[name] = {
        "image": tag,
        "command": ["python", "/lane-tests/L13/proof-service.py"],
        "environment": {
            "TEST_DATABASE_ADMIN_URL": "${TEST_DATABASE_ADMIN_URL}",
            "BT_SERVICE_NAME": name,
            "BT_MODULES_PATH": "/app/modules",
            "PYTHONPATH": "/app:/opt/domain-contracts",
            "L13_STATE_DIR": "/tmp/l13-proof",
            "L13_PORT": "8000",
            "L13_BIND": "0.0.0.0",
        },
        "ports": [f"127.0.0.1:{port}:8000"],
        "networks": ["proof"],
        "read_only": True,
        "tmpfs": ["/tmp"],
        "init": True,
        "mem_limit": "256m",
        "cpus": 0.5,
        "pids_limit": 128,
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2)",
            ],
            "interval": "2s",
            "timeout": "3s",
            "start_period": "5s",
            "retries": 15,
        },
    }
path = ROOT / ".venv/l13-proof-compose.json"
path.write_text(
    json.dumps(
        {
            "services": services,
            "networks": {"proof": {"external": True, "name": network}},
        },
        indent=2,
    )
)
compose = [
    "docker",
    "compose",
    "-p",
    "bt-l13-proof-" + slug + "-" + str(os.getpid()),
    "-f",
    str(path),
]
try:
    subprocess.run(
        [*compose, "up", "-d", "--wait", "--wait-timeout", "90"], check=True, env=env
    )
    for port in (58136, 58137, 58138):
        if (
            httpx.get(f"http://127.0.0.1:{port}/health/ready", timeout=3).status_code
            != 200
        ):
            raise RuntimeError("Compose readiness failed")
    print(
        "PASS three reused Docker domain images, current-source suites and three-service Compose readiness"
    )
finally:
    subprocess.run([*compose, "stop", "--timeout", "20"], env=env, check=False)
