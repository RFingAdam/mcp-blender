"""Blender-free tests for the Python switch, the preferences move and configure-backend keys."""

import ast
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
ADDON = ROOT_DIR / "addon" / "blender_mcp_addon"
ROOT = "_security_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


def _fresh(monkeypatch, bpy):
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)


@pytest.fixture
def ai(monkeypatch):
    _fresh(monkeypatch, MagicMock())
    for name, path in [
        (ROOT, ADDON),
        (f"{ROOT}.handlers", ADDON / "handlers"),
        (f"{ROOT}.external", ADDON / "external"),
    ]:
        monkeypatch.setitem(sys.modules, name, _package(name, path))
    mixin = importlib.import_module(f"{ROOT}.handlers.ai").AIHandlersMixin()
    security = importlib.import_module(f"{ROOT}.security")
    yield types.SimpleNamespace(mixin=mixin, security=security)
    security.set_python_allowed(False)
    for name in [m for m in sys.modules if m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


class _Base:
    pass


def _stub_bpy():
    bpy = MagicMock()
    bpy.types.Operator = _Base
    bpy.types.Panel = _Base
    bpy.types.AddonPreferences = _Base
    bpy.types.Scene = types.SimpleNamespace()
    bpy.context.preferences.addons = {}
    return bpy


@pytest.fixture
def addon(monkeypatch):
    """The real top-level add-on package, imported against a stub bpy."""
    bpy = _stub_bpy()
    _fresh(monkeypatch, bpy)
    spec = importlib.util.spec_from_file_location(
        ROOT, ADDON / "__init__.py", submodule_search_locations=[str(ADDON)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[ROOT] = module
    spec.loader.exec_module(module)
    yield module, bpy
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


# --- Python switch ---------------------------------------------------------------


def test_execute_script_refused_while_python_off(ai):
    ai.security.set_python_allowed(False)
    res = ai.mixin._handle_execute_script({"script": "raise SystemExit('ran')"})
    assert res["success"] is False
    assert res["error"] == ai.security.PYTHON_OFF_ERROR


def test_python_is_off_by_default(ai):
    assert ai.security.python_allowed() is False


def test_execute_script_runs_once_allowed(ai):
    ai.security.set_python_allowed(True)
    res = ai.mixin._handle_execute_script({"script": "result = 6 * 7"})
    assert res["success"] is True
    assert res["result"] == 42


def test_only_the_panel_operator_and_harness_set_the_flag():
    offenders = []
    for base in (ROOT_DIR / "addon", ROOT_DIR / "src"):
        for path in base.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name == "set_python_allowed" and path != ADDON / "__init__.py":
                    offenders.append(str(path.relative_to(ROOT_DIR)))
    assert offenders == []


# --- configure_backend keys ------------------------------------------------------


@pytest.mark.parametrize("key", ["workflow", "python_path", "model_path", "api_base_url"])
def test_configure_backend_rejects_unknown_keys(ai, key):
    res = ai.mixin._handle_ai_configure_backend({"backend": "comfyui", "config": {key: "x"}})
    assert res["success"] is False
    assert key in res["error"]
    if key != "api_base_url":
        assert "Preferences (Meshwire add-on)" in res["error"]


def test_rejected_python_path_names_the_triposr_field(ai):
    res = ai.mixin._handle_ai_configure_backend(
        {"backend": "triposr", "config": {"python_path": "/bin/sh"}}
    )
    assert res["success"] is False
    assert "TripoSR Python" in res["error"]
    assert "Preferences (Meshwire add-on)" in res["error"]


def test_rejected_api_base_url_is_not_a_setting(ai):
    res = ai.mixin._handle_ai_configure_backend(
        {"backend": "comfyui", "config": {"api_base_url": "http://x"}}
    )
    assert res["success"] is False
    assert "api_base_url is not a setting ai_configure_backend accepts" in res["error"]
    assert "Preferences" not in res["error"].split("Allowed keys")[0]


def _triposr(monkeypatch, prefs):
    mod = importlib.import_module(f"{ROOT}.external.ai_backends.triposr")
    root = sys.modules[ROOT]
    root.get_preferences = lambda: prefs
    from types import SimpleNamespace as NS

    backend = mod.TripoSRBackend.__new__(mod.TripoSRBackend)
    backend.config = NS(extra={}, model_path=None)
    return backend


def test_triposr_uses_the_preferences_python_when_set(ai, monkeypatch):
    prefs = types.SimpleNamespace(
        triposr_python="/opt/py/bin/python", triposr_path="/opt/triposr", triposr_model="m"
    )
    backend = _triposr(monkeypatch, prefs)
    assert backend._python_path == "/opt/py/bin/python"
    assert backend._triposr_path == "/opt/triposr"


def test_triposr_defaults_to_python3_without_a_preference(ai, monkeypatch):
    assert _triposr(monkeypatch, None)._python_path == "python3"
    empty = types.SimpleNamespace(triposr_python="", triposr_path="", triposr_model="")
    backend = _triposr(monkeypatch, empty)
    assert backend._python_path == "python3"
    assert backend._triposr_path is None


@pytest.mark.parametrize("host", ["file:///etc/passwd", "http://u:p@h", "ftp://h", "not a url"])
def test_configure_backend_rejects_non_http_host(ai, host):
    res = ai.mixin._handle_ai_configure_backend({"backend": "comfyui", "config": {"host": host}})
    assert res["success"] is False
    assert "host" in res["error"]


@pytest.mark.parametrize(
    "model", ["", "x" * 129, "a b", "../../etc/passwd;", "m\n", 7, None, "llama3.2-vision:11b\x00"]
)
def test_configure_backend_rejects_bad_model_names(ai, model):
    res = ai.mixin._handle_ai_configure_backend(
        {"backend": "ollama_vision", "config": {"model": model}}
    )
    assert res["success"] is False
    assert "model must be" in res["error"]


def test_configure_backend_accepts_an_ollama_model_name(ai):
    res = ai.mixin._handle_ai_configure_backend(
        {"backend": "ollama_vision", "config": {"model": "llama3.2-vision:11b"}}
    )
    assert res.get("success") is True, res


def test_configure_backend_accepts_safe_keys(ai):
    config = {
        "enabled": True,
        "timeout": 60,
        "device": "cpu",
        "host": "http://127.0.0.1:8188",
    }
    res = ai.mixin._handle_ai_configure_backend({"backend": "comfyui", "config": config})
    assert res.get("success") is True, res


# --- settings are Preferences ------------------------------------------------------


def test_settings_are_not_scene_properties(addon):
    module, bpy = addon
    module.register()
    assert not hasattr(module, "MCPServerProperties")
    assert not hasattr(bpy.types.Scene, "mcp_server_props")
    assert "mcp_server_props" not in (ADDON / "__init__.py").read_text()


def test_addon_id_is_the_package(addon):
    module, _ = addon
    assert module.ADDON_ID == ROOT
    assert module.MeshwirePreferences.bl_idname == ROOT


def test_preferences_fall_back_to_defaults_when_unregistered(addon):
    module, _ = addon
    assert module.get_preferences() is None
    assert module.server_address() == ("127.0.0.1", 0)


def test_start_reports_bind_failure(addon, monkeypatch):
    module, _ = addon

    class Dead:
        def __init__(self, host, port):
            self.is_running = False

        def start(self):
            raise module.BindError("Port 9876 on 127.0.0.1 is already in use.")

    monkeypatch.setattr(module, "MCPSocketServer", Dead)
    op = types.SimpleNamespace(report=MagicMock())
    result = module.MCP_OT_StartServer.execute(op, MagicMock())
    assert result == {"CANCELLED"}
    assert module.get_server() is None
    level, message = op.report.call_args[0]
    assert level == {"ERROR"}
    assert message == "Port 9876 on 127.0.0.1 is already in use."


def test_toggle_python_operator_flips_the_flag(addon):
    module, _ = addon
    op = types.SimpleNamespace(report=MagicMock())
    try:
        module.MESHWIRE_OT_TogglePython.execute(op, MagicMock())
        assert module.security.python_allowed() is True
        module.MESHWIRE_OT_TogglePython.execute(op, MagicMock())
        assert module.security.python_allowed() is False
    finally:
        module.security.set_python_allowed(False)


# --- an older copy of the add-on --------------------------------------------------


def test_legacy_id_is_the_old_module_name(addon):
    module, _ = addon
    assert module.LEGACY_ADDON_ID == "blender_mcp_addon"


def test_old_addon_enabled_blocks_start_and_warns(addon, monkeypatch):
    module, bpy = addon
    bpy.context.preferences.addons = {module.LEGACY_ADDON_ID: object()}
    started = []
    monkeypatch.setattr(module, "MCPSocketServer", lambda *a, **k: started.append(1))
    op = types.SimpleNamespace(report=MagicMock())
    assert module.MCP_OT_StartServer.execute(op, MagicMock()) == {"CANCELLED"}
    assert started == []
    assert module.get_server() is None
    level, message = op.report.call_args[0]
    assert level == {"ERROR"}
    assert module.LEGACY_WARNING in message

    layout = MagicMock()
    module.MCP_PT_ServerPanel.draw(types.SimpleNamespace(layout=layout), MagicMock())
    assert module.LEGACY_WARNING == (
        "An older Meshwire add-on (blender_mcp_addon) is still enabled. "
        "Remove it in Preferences > Add-ons, then restart Blender."
    )
    texts = [c.kwargs.get("text") for c in layout.label.call_args_list]
    assert module.LEGACY_WARNING in texts
    layout.operator.assert_not_called()


def test_old_addon_absent_starts_normally(addon, monkeypatch):
    module, bpy = addon
    bpy.context.preferences.addons = {}
    assert module.legacy_addon_enabled() is False

    class Live:
        is_running = True
        port = 9876
        discovery_warning = ""

        def __init__(self, host, port):
            pass

        def start(self):
            pass

    monkeypatch.setattr(module, "MCPSocketServer", Live)
    op = types.SimpleNamespace(report=MagicMock())
    try:
        assert module.MCP_OT_StartServer.execute(op, MagicMock()) == {"FINISHED"}
    finally:
        module._server = None


def test_harness_name_never_warns_about_itself(addon):
    """Loaded under the old name, the add-on is the old copy: it must not block itself."""
    module, bpy = addon
    module.ADDON_ID = module.LEGACY_ADDON_ID
    bpy.context.preferences.addons = {module.LEGACY_ADDON_ID: object()}
    assert module.legacy_addon_enabled() is False
