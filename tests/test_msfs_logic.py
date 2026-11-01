"""Blender-free tests for MSFS helper logic.

The modules import bpy at the top, so a stub stands in for it. The addon
package __init__ files are bypassed with empty namespace packages: only the
module under test and its direct imports run.
"""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADDON = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon"
ROOT = "_msfs_logic_addon"


def _package(name: str, path: Path) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
    return mod


@pytest.fixture
def msfs(monkeypatch):
    bpy = MagicMock()
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    for name in [m for m in sys.modules if m == ROOT or m.startswith(ROOT + ".")]:
        monkeypatch.delitem(sys.modules, name)
    for name, path in [
        (ROOT, ADDON),
        (f"{ROOT}.msfs", ADDON / "msfs"),
        (f"{ROOT}.msfs.livery", ADDON / "msfs" / "livery"),
    ]:
        monkeypatch.setitem(sys.modules, name, _package(name, path))
    transfer = importlib.import_module(f"{ROOT}.msfs.livery.transfer")
    export = importlib.import_module(f"{ROOT}.msfs.export")
    validation = importlib.import_module(f"{ROOT}.validation")
    yield types.SimpleNamespace(bpy=bpy, transfer=transfer, export=export, validation=validation)
    for name in [m for m in sys.modules if m.startswith(ROOT + ".")]:
        sys.modules.pop(name, None)


def _fake_image(msfs, rgb, size=(4, 4)):
    img = MagicMock()
    img.size = size
    img.pixels = [*rgb, 1.0] * (size[0] * size[1])
    msfs.bpy.data.images.load.return_value = img


def test_all_white_image_gets_a_note(msfs, tmp_path):
    png = tmp_path / "white.png"
    png.write_bytes(b"x")
    _fake_image(msfs, (1.0, 1.0, 1.0))
    out = msfs.transfer.extract_color_palette(str(png), exclude_white=True)
    assert out["palette"] == [] and out["count"] == 0
    assert "white" in out["note"]


def test_all_white_image_kept_when_not_excluded(msfs, tmp_path):
    png = tmp_path / "white.png"
    png.write_bytes(b"x")
    _fake_image(msfs, (1.0, 1.0, 1.0))
    out = msfs.transfer.extract_color_palette(str(png), exclude_white=False)
    assert out["count"] == 1 and "note" not in out


def test_exclude_white_drops_white_and_percentage_is_of_kept_samples(msfs):
    pixels = [1.0, 1.0, 1.0, 1.0] * 30 + [0.75, 0.3, 0.1, 1.0] * 10
    colors = msfs.transfer._extract_dominant_colors(pixels, 8, 5, num_colors=4, exclude_white=True)
    assert len(colors) == 1
    assert colors[0]["percentage"] == 100.0


def test_map_design_elements_none_maps_every_type(msfs):
    out = msfs.transfer.map_design_elements("fbw_a32nx", "pmdg_737")
    assert {e["type"] for e in out["mapped_elements"]} == set(msfs.transfer.DESIGN_ELEMENTS)


def test_map_design_elements_accepts_names_and_dicts(msfs):
    out = msfs.transfer.map_design_elements(
        "fbw_a32nx", "pmdg_737", ["cheatline", {"type": "flag", "position": {}}]
    )
    assert [e["type"] for e in out["mapped_elements"]] == ["cheatline", "flag"]


def test_map_design_elements_reports_unknown_names(msfs):
    out = msfs.transfer.map_design_elements("fbw_a32nx", "pmdg_737", ["cheatline", "logoo"])
    assert "logoo" in out["error"] and "mapped_elements" not in out


def test_map_design_elements_rejects_other_item_types(msfs):
    out = msfs.transfer.map_design_elements("fbw_a32nx", "pmdg_737", [3])
    assert "error" in out


def test_export_rejects_unknown_format_before_touching_blender(msfs):
    with pytest.raises(msfs.validation.ValidationError, match="export_format"):
        msfs.export.export_msfs_model("/tmp/x.glb", export_format="OBJ")
    assert not msfs.bpy.ops.export_scene.gltf.called


def test_exporter_format_names(msfs):
    assert msfs.export._EXPORTER_FORMATS == {"GLB": "GLB", "GLTF": "GLTF_SEPARATE"}
