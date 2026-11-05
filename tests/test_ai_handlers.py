"""Blender-free tests for the AI handlers: redo by job kind and the variation cap."""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_ai_handlers_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy", MagicMock())
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    for name, path in [
        (ROOT, ADDON),
        (f"{ROOT}.handlers", ADDON / "handlers"),
        (f"{ROOT}.external", ADDON / "external"),
    ]:
        monkeypatch.setitem(sys.modules, name, _package(name, path))
    mixin = importlib.import_module(f"{ROOT}.handlers.ai").AIHandlersMixin()
    models = importlib.import_module(f"{ROOT}.external.ai_models")
    queue_mod = importlib.import_module(f"{ROOT}.external.job_queue")
    yield types.SimpleNamespace(mixin=mixin, models=models, queue_mod=queue_mod)
    for name in [m for m in sys.modules if m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


def _last_job(ai, monkeypatch, **fields):
    job = types.SimpleNamespace(
        prompt="a wing",
        style=None,
        quality="medium",
        output_format="glb",
        backend="auto",
        image_path=None,
        metadata={},
    )
    for key, value in fields.items():
        setattr(job, key, value)
    queue = MagicMock()
    queue.get_last_job.return_value = job
    monkeypatch.setattr(ai.queue_mod, "get_job_queue", lambda: queue)
    return job


def test_redo_replays_a_texture_job_as_a_texture(ai, monkeypatch):
    _last_job(
        ai,
        monkeypatch,
        prompt="rusty metal",
        output_format="png",
        metadata={
            "kind": "texture",
            "workflow_type": "pbr_texture",
            "object_name": "Wing",
            "auto_apply": False,
        },
    )
    texture = MagicMock(return_value={"success": True})
    model = MagicMock()
    monkeypatch.setattr(ai.models, "generate_texture", texture)
    monkeypatch.setattr(ai.models, "generate_model", model)
    assert ai.mixin._handle_ai_redo_generation({}) == {"success": True}
    model.assert_not_called()
    kwargs = texture.call_args.kwargs
    assert kwargs["prompt"] == "rusty metal"
    assert kwargs["workflow_type"] == "pbr_texture"
    assert kwargs["object_name"] == "Wing"
    assert kwargs["auto_apply"] is False


def test_redo_replays_a_model_job_as_a_model(ai, monkeypatch):
    _last_job(ai, monkeypatch, metadata={"kind": "model"})
    model = MagicMock(return_value={"success": True})
    monkeypatch.setattr(ai.models, "generate_model", model)
    assert ai.mixin._handle_ai_redo_generation({}) == {"success": True}
    assert model.call_args.kwargs["prompt"] == "a wing"


def test_redo_refuses_a_job_kind_it_cannot_replay(ai, monkeypatch):
    _last_job(ai, monkeypatch, metadata={"kind": "mystery"})
    model = MagicMock()
    monkeypatch.setattr(ai.models, "generate_model", model)
    reply = ai.mixin._handle_ai_redo_generation({})
    assert reply["success"] is False
    assert "mystery" in reply["error"]
    model.assert_not_called()


def test_generators_record_the_job_kind(ai, monkeypatch):
    queue = MagicMock()
    queue.create_job.return_value = types.SimpleNamespace(id="j1")
    monkeypatch.setattr(ai.models, "get_job_queue", lambda: queue)
    manager = MagicMock()
    ok = types.SimpleNamespace(
        success=True,
        job_id="x",
        status=types.SimpleNamespace(value="pending"),
        metadata={},
        error=None,
    )
    manager.generate_model.return_value = ok
    manager.generate_texture.return_value = ok
    manager.generate_model_from_image.return_value = ok
    monkeypatch.setattr(ai.models, "get_backend_manager", lambda: manager)
    ai.models.generate_model(prompt="a wing")
    ai.models.generate_texture(prompt="rust")
    kinds = [c.kwargs["metadata"]["kind"] for c in queue.create_job.call_args_list]
    assert kinds == ["model", "texture"]


def test_variations_above_the_cap_are_refused(ai, monkeypatch):
    model = MagicMock()
    monkeypatch.setattr(ai.models, "generate_model", model)
    validation = importlib.import_module(f"{ROOT}.validation")
    with pytest.raises(validation.ValidationError, match="8"):
        ai.mixin._handle_ai_generate_variations({"prompt": "a wing", "num_variations": 50})
    model.assert_not_called()
