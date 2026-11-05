"""object_separate must not leave the scene in Edit mode when the operator raises."""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_object_separate_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


@pytest.fixture
def objects(monkeypatch):
    bpy = MagicMock()
    bpy.context.mode = "OBJECT"

    def mode_set(mode):
        bpy.context.mode = "EDIT_MESH" if mode == "EDIT" else mode

    bpy.ops.object.mode_set.side_effect = lambda mode: mode_set(mode)
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    for name, path in [(ROOT, ADDON), (f"{ROOT}.handlers", ADDON / "handlers")]:
        monkeypatch.setitem(sys.modules, name, _package(name, path))
    mod = importlib.import_module(f"{ROOT}.handlers.objects")
    yield types.SimpleNamespace(bpy=bpy, mixin=mod.ObjectHandlersMixin())
    for name in [m for m in sys.modules if m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


def test_a_raising_separate_returns_to_object_mode(objects):
    objects.bpy.ops.mesh.separate.side_effect = RuntimeError("one material slot")
    with pytest.raises(RuntimeError):
        objects.mixin._handle_object_separate({"name": "Cube", "mode": "MATERIAL"})
    assert objects.bpy.context.mode == "OBJECT"
