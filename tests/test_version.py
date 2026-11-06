"""One version for the whole project, and a working --version flag."""

from __future__ import annotations

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest

import mcp_blender
from mcp_blender import server

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, which only unit tests run on
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent


ADDON = ROOT / "addon" / "blender_mcp_addon"


def _manifest() -> dict:
    return tomllib.loads((ADDON / "blender_manifest.toml").read_text())


def _release() -> str:
    return mcp_blender.__version__.split("a")[0].split("b")[0].split("rc")[0]


def _packager():
    spec = importlib.util.spec_from_file_location(
        "package_addon", ROOT / "scripts" / "package_addon.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_is_pep440():
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?", mcp_blender.__version__)


def test_manifest_version_matches_package():
    assert _manifest()["version"] == _release()


def test_packager_reads_the_manifest_version():
    assert _packager().get_version() == _manifest()["version"]


def test_zip_has_manifest_at_root(tmp_path, capsys):
    out = tmp_path / f"meshwire-addon-{_release()}.zip"
    assert _packager().package_addon(out)
    names = zipfile.ZipFile(out).namelist()
    assert "blender_manifest.toml" in names
    assert "__init__.py" in names
    assert not any(n.startswith("blender_mcp_addon/") for n in names)
    assert not any("__pycache__" in n or n.endswith((".pyc", ".pyo")) for n in names)
    assert not any(part.startswith(".") for n in names for part in n.split("/"))
    assert not any(n.startswith("tests") for n in names)
    inside = tomllib.loads(zipfile.ZipFile(out).read("blender_manifest.toml").decode())
    assert inside["version"] == _release()


def test_default_zip_name(monkeypatch, tmp_path):
    module = _packager()
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "ADDON_DIR", ADDON)
    assert module.package_addon()
    assert (tmp_path / "dist" / f"meshwire-addon-{_release()}.zip").is_file()


def test_manifest_fields():
    m = _manifest()
    assert m["schema_version"] == "1.0.0"
    assert m["id"] == "meshwire"
    assert m["type"] == "add-on"
    assert m["blender_version_min"] == "4.2.0"
    assert m["license"] == ["SPDX:AGPL-3.0-or-later"]
    assert set(m["permissions"]) == {"network", "files"}


def test_no_literal_addon_module_name():
    hits = []
    for path in ADDON.rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "blender_mcp_addon" in line and not line.startswith(
                'LEGACY_ADDON_ID = "blender_mcp_addon"'
            ):
                hits.append(f"{path.relative_to(ROOT)}:{n}")
    assert hits == []


def test_no_bl_info():
    for path in ADDON.rglob("*.py"):
        assert "bl_info" not in path.read_text(), path


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


def test_server_reports_the_manifest_version(monkeypatch):
    """hello and the instance file take the add-on version from the manifest next to the code."""
    import sys
    import types
    from unittest.mock import MagicMock

    monkeypatch.setitem(sys.modules, "bpy", MagicMock())
    for name in ("_ver_addon", "_ver_addon.handlers"):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["_ver_addon"].__path__ = [str(ADDON)]
    sys.modules["_ver_addon.handlers"].CommandHandlers = object
    try:
        spec = importlib.util.spec_from_file_location(
            "_ver_addon.socket_server", ADDON / "socket_server.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ver_addon.socket_server"] = module
        spec.loader.exec_module(module)
        assert module.MCPSocketServer._addon_version() == _manifest()["version"]
    finally:
        for name in [n for n in sys.modules if n.startswith("_ver_addon")]:
            del sys.modules[name]
