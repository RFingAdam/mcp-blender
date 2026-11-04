"""Blender-free tests for the bake scene capture and restore.

The module imports bpy at the top, so a stub stands in for it, and the addon
package __init__ files are bypassed (see test_msfs_logic.py).
"""

import copy
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_bake_restore_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


@pytest.fixture
def baking(monkeypatch):
    bpy = MagicMock()
    bpy.app.version = (4, 5, 0)
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    for name, path in [(ROOT, ADDON), (f"{ROOT}.handlers", ADDON / "handlers")]:
        monkeypatch.setitem(sys.modules, name, _package(name, path))
    module = importlib.import_module(f"{ROOT}.handlers.baking")
    yield types.SimpleNamespace(bpy=bpy, module=module)
    for name in [m for m in sys.modules if m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


def _prop(identifier, readonly=False, kind="ENUM"):
    return types.SimpleNamespace(identifier=identifier, is_readonly=readonly, type=kind)


class FakeRender:
    """``engine`` refuses the value it was captured with, as an unavailable add-on engine does."""

    def __init__(self, engine="LUXCORE"):
        self.bl_rna = types.SimpleNamespace(
            properties=[
                _prop("engine"),
                _prop("bake_samples", kind="INT"),
                _prop("frame_current", readonly=True),
            ]
        )
        self.__dict__.update(engine=engine, bake_samples=4, frame_current=1)
        self.bake = FakeBake()
        self.refuse_engine = False

    def __setattr__(self, name, value):
        if name == "engine" and getattr(self, "refuse_engine", False) and value == "LUXCORE":
            raise TypeError("enum 'LUXCORE' not found in ('CYCLES', 'BLENDER_EEVEE')")
        if name == "frame_current" and "frame_current" in self.__dict__:
            raise AttributeError("read-only")
        object.__setattr__(self, name, value)


class FakeBake:
    def __init__(self):
        self.bl_rna = types.SimpleNamespace(properties=[_prop("margin", kind="INT")])
        self.margin = 16


def _scene(baking, render):
    scene = types.SimpleNamespace(render=render)
    baking.bpy.context.scene = scene
    layer = MagicMock()
    layer.objects = MagicMock()
    layer.objects.__iter__.return_value = iter([])
    baking.bpy.context.view_layer = layer
    return scene


def _handler(baking):
    return baking.module.BakingHandlersMixin()


def test_unrestorable_engine_is_reported(baking):
    render = FakeRender()
    _scene(baking, render)
    mixin = _handler(baking)
    state = mixin._bake_capture_scene()
    render.engine = "CYCLES"
    render.bake.margin = 2
    render.refuse_engine = True
    unrestored = mixin._bake_restore_scene(state)
    assert len(unrestored) == 1
    assert "render.engine" in unrestored[0] and "LUXCORE" in unrestored[0]
    # One failure did not skip the other property.
    assert render.bake.margin == 16
    assert render.engine == "CYCLES"


def test_clean_restore_has_no_warnings_and_skips_read_only(baking):
    render = FakeRender(engine="BLENDER_EEVEE")
    _scene(baking, render)
    mixin = _handler(baking)
    state = mixin._bake_capture_scene()
    assert all(name != "frame_current" for _, _, name, _ in state["values"])
    render.engine = "CYCLES"
    assert mixin._bake_restore_scene(state) == []
    assert render.engine == "BLENDER_EEVEE"


@pytest.mark.parametrize("result", [{"success": True}, {"error": "boom", "warnings": ["earlier"]}])
def test_decorator_adds_warning_and_keeps_the_rest(baking, result):
    render = FakeRender()
    _scene(baking, render)

    class Handler(baking.module.BakingHandlersMixin):
        @baking.module._restores_scene
        def run(self, params):
            render.engine = "CYCLES"
            render.refuse_engine = True
            return copy.deepcopy(result)

    out = Handler().run({})
    assert "render.engine" in out["warnings"][-1]
    assert out.get("error") == result.get("error")
    assert out["warnings"][:-1] == result.get("warnings", [])
