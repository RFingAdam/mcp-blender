"""Blender-free tests for which replies push an undo step.

The addon package __init__ files are bypassed, as in test_bake_restore.py, and
bpy is a stub.
"""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.result_cases import RESULT_CASES

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_undo_gating_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


@pytest.fixture
def handlers(monkeypatch):
    bpy = MagicMock()
    bpy.app.background = False
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, ROOT, _package(ROOT, ADDON))
    monkeypatch.setitem(
        sys.modules, f"{ROOT}.external", _package(f"{ROOT}.external", ADDON / "external")
    )
    mod = importlib.import_module(f"{ROOT}.handlers")
    yield types.SimpleNamespace(mod=mod, bpy=bpy)
    for name in [m for m in sys.modules if m.startswith(ROOT)]:
        sys.modules.pop(name, None)


def test_execute_script_reply_shape_counts_as_success(handlers):
    assert handlers.mod._succeeded({"success": True, "error": None}) is True


def test_execute_script_success_pushes_undo(handlers):
    h = _handlers_with(handlers, "execute_script", {"success": True, "error": None, "output": ""})
    h.handle("execute_script", {})
    handlers.bpy.ops.ed.undo_push.assert_called_once_with(message="execute_script")


@pytest.mark.parametrize(("reply", "failed"), RESULT_CASES)
def test_succeeded_matches_shared_table(handlers, reply, failed):
    assert handlers.mod._succeeded(reply) is (not failed)


def test_error_and_success_false_count_as_failures(handlers):
    assert handlers.mod._succeeded({"error": "x"}) is False
    assert handlers.mod._succeeded({"success": False}) is False
    assert handlers.mod._succeeded({"success": True}) is True
    assert handlers.mod._succeeded(["not", "a", "dict"]) is True


def _handlers_with(handlers, name, reply):
    h = handlers.mod.CommandHandlers()
    h._handlers[name] = lambda params: dict(reply)
    return h


def test_execute_script_pushes_an_undo_step(handlers):
    h = _handlers_with(handlers, "execute_script", {"success": True, "error": None})
    h.handle("execute_script", {})
    handlers.bpy.ops.ed.undo_push.assert_called_once_with(message="execute_script")


def test_model_status_poll_that_imports_nothing_pushes_no_step(handlers):
    h = _handlers_with(handlers, "ai_model_status", {"success": True, "status": "processing"})
    out = h.handle("ai_model_status", {})
    handlers.bpy.ops.ed.undo_push.assert_not_called()
    assert out == {"success": True, "status": "processing"}


def test_model_status_import_pushes_one_step_and_hides_the_marker(handlers):
    h = _handlers_with(
        handlers,
        "ai_model_status",
        {
            "success": True,
            "status": "completed",
            "imported": {"success": True},
            "_pushed_changes": True,
        },
    )
    out = h.handle("ai_model_status", {})
    handlers.bpy.ops.ed.undo_push.assert_called_once_with(message="ai_model_status")
    assert "_pushed_changes" not in out


def test_model_status_handler_marks_only_a_real_import(handlers, monkeypatch):
    ai = importlib.import_module(f"{ROOT}.external.ai_models")
    mixin = importlib.import_module(f"{ROOT}.handlers.ai").AIHandlersMixin()
    monkeypatch.setattr(ai, "check_status", lambda **kw: {"success": True, "status": "processing"})
    assert "_pushed_changes" not in mixin._handle_ai_model_status({"job_id": "j"})
    monkeypatch.setattr(
        ai,
        "check_status",
        lambda **kw: {"success": True, "status": "completed", "imported": {"success": True}},
    )
    assert mixin._handle_ai_model_status({"job_id": "j"})["_pushed_changes"] is True
