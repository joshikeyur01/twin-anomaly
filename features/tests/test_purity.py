"""Architectural tripwires for the feature contract.

STYLE.md: features/ is numpy-only with no I/O of any kind. These tests make
that a build failure instead of a review comment.
"""

import ast
import pathlib
import re

import features

SRC = pathlib.Path(__file__).parent.parent / "src" / "features"

# Modules whose presence in features/ would mean skew or hidden I/O is back.
FORBIDDEN_IMPORTS = {
    "pandas",
    "pydantic",
    "pyarrow",
    "influxdb_client",
    "sklearn",
    "torch",
    "aiomqtt",
    "requests",
    "httpx",
}


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", features.__version__)


def test_numpy_only() -> None:
    for module in SRC.rglob("*.py"):
        forbidden = _imported_roots(module) & FORBIDDEN_IMPORTS
        assert not forbidden, f"{module.name} imports {sorted(forbidden)}"


def test_no_file_io() -> None:
    # `open(` in feature code means a dataset or config snuck in below the
    # pipeline boundary. Windows arrive as arrays or not at all.
    for module in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            is_open = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            )
            assert not is_open, f"{module.name} calls open()"
