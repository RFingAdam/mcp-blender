"""Blender-free tests that handlers do their file I/O on the resolved path.

``~`` and Blender-relative ``//`` mean something to the user and nothing to
``os``, so a handler resolves first, writes there, and replies with that path.
The addon package ``__init__`` files are bypassed, as in test_bake_restore.py.
"""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_path_handlers_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


@pytest.fixture
def addon(monkeypatch, tmp_path):
    bpy = MagicMock()
    blend_dir = tmp_path / "project"
    bpy.path.abspath.side_effect = lambda p: str(blend_dir / p[2:]) if p.startswith("//") else p
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    for name, path in [(ROOT, ADDON), (f"{ROOT}.handlers", ADDON / "handlers")]:
        monkeypatch.setitem(sys.modules, name, _package(name, path))
    yield types.SimpleNamespace(
        bpy=bpy, blend_dir=blend_dir, import_module=lambda n: importlib.import_module(f"{ROOT}.{n}")
    )
    for name in [m for m in sys.modules if m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


def test_save_as_expands_home_and_replies_with_the_absolute_path(addon, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    mixin = addon.import_module("handlers.collections").CollectionHandlersMixin()
    result = mixin._handle_save_as({"filepath": "~/Documents/plane"})
    expected = str(tmp_path / "Documents" / "plane.blend")
    assert result["filepath"] == expected
    assert (tmp_path / "Documents").is_dir()
    assert addon.bpy.ops.wm.save_as_mainfile.call_args.kwargs["filepath"] == expected
    assert not (Path.cwd() / "~").exists()


def test_save_as_resolves_blender_relative_against_the_blend_file(addon):
    mixin = addon.import_module("handlers.collections").CollectionHandlersMixin()
    result = mixin._handle_save_as({"filepath": "//saves/plane.blend"})
    assert result["filepath"] == str(addon.blend_dir / "saves" / "plane.blend")
    assert (addon.blend_dir / "saves").is_dir()
