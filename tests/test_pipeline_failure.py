"""ai_pipeline_generate must report a failed stage at the top level."""

import importlib.util
from pathlib import Path

PIPELINE = (
    Path(__file__).resolve().parent.parent
    / "addon"
    / "blender_mcp_addon"
    / "external"
    / "pipeline.py"
)


def _pipeline():
    spec = importlib.util.spec_from_file_location("pipeline_under_test", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Handlers:
    """Stub handler set: each method returns a canned reply."""

    def __init__(self, generate, import_file=None):
        self._generate = generate
        self._import = import_file or {"success": True, "imported_objects": ["Mesh"]}

    def _handle_ai_generate_reference_image(self, params):
        return {"success": False, "error": "offline"}

    def _handle_ai_generate_model_sync(self, params):
        return self._generate

    def _handle_import_file(self, params):
        return self._import


def test_failed_generate_stage_is_a_top_level_failure():
    mod = _pipeline()
    handlers = _Handlers({"success": False, "error": "no backend"})
    out = mod.run_pipeline({"pipeline_preset": "quick", "prompt": "a cube"}, handlers)
    assert out["success"] is False
    assert "no backend" in out["error"]
    assert out["stages"]["generate"]["status"] == "failed"


def test_failed_import_stage_is_a_top_level_failure():
    mod = _pipeline()
    handlers = _Handlers(
        {"success": True, "mesh_path": "/x.glb"},
        import_file={"success": False, "error": "bad file"},
    )
    out = mod.run_pipeline({"pipeline_preset": "quick", "prompt": "a cube"}, handlers)
    assert out["success"] is False
    assert out["stages"]["import"]["status"] == "failed"


def test_all_stages_completing_reports_success():
    mod = _pipeline()
    handlers = _Handlers({"success": True, "mesh_path": "/x.glb"})
    out = mod.run_pipeline(
        {"pipeline_preset": "quick", "prompt": "a cube", "skip_stages": ["texture"]}, handlers
    )
    assert out["success"] is True
    assert "error" not in out
