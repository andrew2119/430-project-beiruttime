"""Portable check configuration with project-local defaults."""

import os
from pathlib import Path


def configured_path(name: str, default: Path, root: Path) -> Path:
    value = Path(os.environ.get(name) or default).expanduser()
    return (value if value.is_absolute() else root / value).resolve()


def tool_bin(root: Path) -> Path:
    root = root.resolve()
    return configured_path("BT_TOOLS_BIN", root / "web/node_modules/.bin", root)


def contracts_dir(root: Path) -> Path:
    root = root.resolve()
    return configured_path("BT_CONTRACTS_DIR", root / "tests/lanes/L13/.contracts", root)
