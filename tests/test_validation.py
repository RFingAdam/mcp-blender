"""Tests for addon parameter validation helpers (loaded without bpy)."""

import importlib.util
import os
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "addon" / "blender_mcp_addon" / "validation.py"
_spec = importlib.util.spec_from_file_location("meshwire_validation", _PATH)
validation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validation)

validate_filepath = validation.validate_filepath
ValidationError = validation.ValidationError


def test_validate_filepath_expands_home():
    assert validate_filepath("~/x.png", "p") == os.path.join(os.path.expanduser("~"), "x.png")


def test_validate_filepath_checks_existence_after_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "a.png").write_bytes(b"x")
    assert validate_filepath("~/a.png", "p", must_exist=True) == str(tmp_path / "a.png")


def test_validate_filepath_missing_file_after_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValidationError, match="File not found"):
        validate_filepath("~/nope.png", "p", must_exist=True)


def test_validate_filepath_makes_relative_paths_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert validate_filepath("out/a.png", "p") == str(tmp_path / "out" / "a.png")


@pytest.fixture
def stub_bpy(monkeypatch, tmp_path):
    """A bpy whose abspath resolves ``//`` against a fake .blend directory."""
    import sys
    import types

    blend_dir = tmp_path / "project"

    def abspath(path):
        return str(blend_dir / path[2:]) if path.startswith("//") else path

    stub = types.ModuleType("bpy")
    stub.path = types.SimpleNamespace(abspath=abspath)
    stub.data = types.SimpleNamespace(filepath=str(blend_dir / "scene.blend"))
    monkeypatch.setitem(sys.modules, "bpy", stub)
    return blend_dir


def test_resolve_path_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert validation.resolve_path("~/bakes") == str(tmp_path / "bakes")


def test_resolve_path_resolves_blender_relative_against_the_blend_file(stub_bpy):
    assert validation.resolve_path("//textures/a.png") == str(stub_bpy / "textures" / "a.png")


def test_blender_relative_path_needs_a_saved_blend_file(stub_bpy, monkeypatch):
    import sys

    monkeypatch.setattr(sys.modules["bpy"].data, "filepath", "")
    with pytest.raises(ValidationError, match="Save the file first"):
        validation.resolve_path("//x.png")
    with pytest.raises(ValidationError, match="Save the file first"):
        validate_filepath("//x.png", "p")
    assert validation.resolve_path("/abs/x.png") == "/abs/x.png"


def test_resolve_path_normalizes_and_makes_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert validation.resolve_path("a/../b//c.png") == str(tmp_path / "b" / "c.png")


def test_resolve_path_leaves_plain_paths_alone_without_bpy(tmp_path):
    assert validation.resolve_path(str(tmp_path / "x")) == str(tmp_path / "x")


def test_validate_filepath_resolves_blender_relative(stub_bpy):
    assert validate_filepath("//renders/a.png", "p") == str(stub_bpy / "renders" / "a.png")


def test_validate_filepath_checks_blender_relative_existence_on_the_resolved_path(stub_bpy):
    (stub_bpy / "renders").mkdir(parents=True)
    (stub_bpy / "renders" / "a.png").write_bytes(b"x")
    assert validate_filepath("//renders/a.png", "p", must_exist=True) == str(
        stub_bpy / "renders" / "a.png"
    )


@pytest.mark.parametrize("bad", [None, 3, "", "   "])
def test_validate_filepath_rejects_non_paths(bad):
    with pytest.raises(ValidationError):
        validate_filepath(bad, "p")
