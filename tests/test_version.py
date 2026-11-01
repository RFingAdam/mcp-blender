"""One version for the whole project, and a working --version flag."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import mcp_blender
from mcp_blender import server

ROOT = Path(__file__).resolve().parent.parent


def _addon_version() -> tuple[int, ...]:
    tree = ast.parse((ROOT / "addon" / "blender_mcp_addon" / "__init__.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id == "bl_info":
            return ast.literal_eval(node.value)["version"]
    raise AssertionError("bl_info not found")


def test_version_is_pep440():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?", mcp_blender.__version__)


def test_addon_version_matches_package():
    release = mcp_blender.__version__.split("a")[0].split("b")[0].split("rc")[0]
    assert ".".join(map(str, _addon_version())) == release


def test_pyproject_takes_version_from_the_package():
    text = (ROOT / "pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in text
    assert 'path = "src/mcp_blender/__init__.py"' in text
    assert not re.search(r'^version = "', text, re.MULTILINE)


def test_addon_does_not_hardcode_a_version_string():
    text = (ROOT / "addon" / "blender_mcp_addon" / "__init__.py").read_text()
    assert not re.search(r"version \d+\.\d+", text)


def test_cli_version_flag(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["meshwire", "--version"])
    with pytest.raises(SystemExit) as exc:
        server.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"meshwire {mcp_blender.__version__}"
