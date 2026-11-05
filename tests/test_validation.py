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


def test_validate_filepath_passes_blender_relative_through():
    assert validate_filepath("//renders/a.png", "p") == "//renders/a.png"


@pytest.mark.parametrize("bad", [None, 3, "", "   "])
def test_validate_filepath_rejects_non_paths(bad):
    with pytest.raises(ValidationError):
        validate_filepath(bad, "p")
