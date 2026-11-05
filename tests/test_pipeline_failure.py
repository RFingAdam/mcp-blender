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


class _MsfsHandlers:
    """Stub handler set for the MSFS prep stage; records the export call."""

    def __init__(self, export):
        self._export = export
        self.export_params = None

    def _handle_msfs_create_lod_hierarchy(self, params):
        return {"success": True}

    def _handle_msfs_create_collision_box(self, params):
        return {"success": True}

    def _handle_msfs_validate_for_export(self, params):
        return {"success": True}

    def _handle_msfs_export_model(self, params):
        self.export_params = dict(params)
        return self._export


def _run_msfs(monkeypatch, handlers, tmp_path):
    import sys
    from unittest.mock import MagicMock

    monkeypatch.setitem(sys.modules, "bpy", MagicMock())
    mod = _pipeline()
    return mod.run_pipeline(
        {
            "pipeline_preset": "msfs_vehicle",
            "existing_object": "Wing",
            "skip_stages": ["cleanup", "uv"],
            "output_dir": str(tmp_path),
        },
        handlers,
    )


def test_msfs_stage_exports_to_a_filepath_built_from_the_output_dir(monkeypatch, tmp_path):
    handlers = _MsfsHandlers({"success": True})
    out = _run_msfs(monkeypatch, handlers, tmp_path)
    assert out["success"] is True
    assert handlers.export_params == {"filepath": str(tmp_path / "Wing.glb")}


def test_msfs_export_failure_reaches_the_pipeline_result(monkeypatch, tmp_path):
    handlers = _MsfsHandlers({"success": False, "error": "disk full"})
    out = _run_msfs(monkeypatch, handlers, tmp_path)
    assert out["success"] is False
    assert "disk full" in out["error"]
    assert out["stages"]["msfs_prep"]["status"] == "failed"
