"""Check path resolution and a tiny publication fixture, without running services."""

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def paths(lane_modules):
    return lane_modules("lane_portable_paths", "tests/lanes/L13/portable_paths.py")


def test_defaults_are_local_and_do_not_create_directories(paths, monkeypatch, tmp_path):
    monkeypatch.delenv("BT_TOOLS_BIN", raising=False)
    monkeypatch.delenv("BT_CONTRACTS_DIR", raising=False)
    assert paths.tool_bin(tmp_path) == tmp_path / "web/node_modules/.bin"
    assert paths.contracts_dir(tmp_path) == tmp_path / "tests/lanes/L13/.contracts"
    assert not (tmp_path / "web").exists()
    assert not (tmp_path / "tests").exists()


@pytest.mark.parametrize("value", ["custom/bin", "", "~/checks"])
def test_environment_overrides_and_empty_default(paths, monkeypatch, tmp_path, value):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BT_TOOLS_BIN", value)
    monkeypatch.setenv("BT_CONTRACTS_DIR", value)
    if value == "":
        assert paths.tool_bin(tmp_path) == tmp_path / "web/node_modules/.bin"
        assert paths.contracts_dir(tmp_path) == tmp_path / "tests/lanes/L13/.contracts"
    else:
        expected = tmp_path / "home/checks" if value.startswith("~") else tmp_path / value
        assert paths.tool_bin(tmp_path) == expected
        assert paths.contracts_dir(tmp_path) == expected


def test_explicit_absolute_output_is_supported(paths, monkeypatch, tmp_path):
    destination = tmp_path / "output"
    monkeypatch.setenv("BT_CONTRACTS_DIR", str(destination))
    assert paths.contracts_dir(tmp_path / "repo") == destination


@pytest.mark.parametrize("filename,target,helper", [
    ("check-browser.py", "TOOLS", "tool_bin"), ("publish-contracts.py", "PUBLISHED", "contracts_dir"),
])
def test_runners_use_the_portable_resolver_without_executing_them(paths, monkeypatch, tmp_path, filename, target, helper):
    monkeypatch.delenv("BT_TOOLS_BIN", raising=False)
    monkeypatch.delenv("BT_CONTRACTS_DIR", raising=False)
    source = (ROOT / "tests/lanes/L13" / filename).read_text()
    tree = ast.parse(source)
    compile(tree, filename, "exec")  # Syntax only: no process, browser, stack or real publication.
    assert any(isinstance(node, ast.ImportFrom) and node.module == "portable_paths"
               and any(name.name == helper for name in node.names) for node in tree.body)
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(name, ast.Name) and name.id == target for name in node.targets))
    assert isinstance(assignment.value, ast.Call) and isinstance(assignment.value.func, ast.Name)
    assert assignment.value.func.id == helper
    value = eval(compile(ast.Expression(assignment.value), filename, "eval"),
                 {"ROOT": tmp_path, helper: getattr(paths, helper)})
    assert value == getattr(paths, helper)(tmp_path)
    assert not any(isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and ("/" + "Users/") in node.value for node in ast.walk(tree))


def test_publisher_keeps_archive_and_exact_manifest_at_selected_destination(tmp_path):
    source = (ROOT / "tests/lanes/L13/publish-contracts.py").read_text()
    tree = ast.parse(source)
    functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                                and node.name in {"files", "publish"}], type_ignores=[])
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "schema.py").write_text("VALUE = 1\n")
    (inputs / "__pycache__").mkdir()
    (inputs / "__pycache__/ignored.pyc").write_bytes(b"not source")
    destination = tmp_path / "selected-output"
    head = "a" * 40

    def git(command, *, cwd, text):
        assert cwd == tmp_path and text is True
        if command[1] == "status":
            return ""
        if command[1] == "rev-parse":
            return head + "\n"
        if command[1] == "branch":
            return "bt/check-fixture\n"
        raise AssertionError(command)

    namespace = {"ROOT": tmp_path, "PUBLISHED": destination, "OMIT": {"__pycache__"},
                 "subprocess": SimpleNamespace(check_output=git), "datetime": datetime, "timezone": timezone,
                 "hashlib": hashlib, "json": json, "tarfile": tarfile}
    exec(compile(functions, "publish-functions", "exec"), namespace)
    published = namespace["publish"]("fixture/v1", ["input"])
    assert published == destination / "fixture/v1"
    manifest = json.loads((published / "implementation-sha256.json").read_text())
    assert manifest["source_commit"] == head
    assert manifest["sha256"] == {"input/schema.py": hashlib.sha256(b"VALUE = 1\n").hexdigest()}
    with tarfile.open(published / "implementation.tar.gz") as archive:
        assert archive.getnames() == ["input/schema.py"]
